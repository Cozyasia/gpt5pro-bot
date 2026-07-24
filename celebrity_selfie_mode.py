# -*- coding: utf-8 -*-
"""Clean Celebrity Selfie mode for Neyro-Bot.

This module replaces the historical celebrity-selfie overlay chain with one
explicit state machine:

    user selfie -> character -> scene -> multi-reference generation -> QC

It also provides a hidden admin catalog where the owner can create a character,
upload 3-6 reference photos and publish the character into the public menu.

The module is designed for python-telegram-bot 21.x and does not monkey-patch
ApplicationBuilder, main.py functions, or provider modules.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

log = logging.getLogger("neyrobot.celebrity-selfie-clean")

VERSION = "v200-celebrity-selfie-clean-rewrite-2026-07-24"

ChargeAndRun = Callable[
    [Update, ContextTypes.DEFAULT_TYPE, str, float, Callable[[], Awaitable[bool]]],
    Awaitable[Any],
]
GetCachedPhoto = Callable[[int], Optional[bytes]]
CachePhoto = Callable[[int, bytes, str], Any]


@dataclass(slots=True)
class CelebritySelfieConfig:
    project_root: str
    data_dir: str
    seed_dir: str
    admin_ids: set[int] = field(default_factory=set)
    enabled: bool = True
    public_button_text: str = "🤳 AI-селфи со звездой"
    hidden_admin_command: str = "star_admin"

    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3-pro-image"
    gemini_fallback_model: str = "gemini-3.1-flash-image"

    openai_image_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_image_model: str = "gpt-image-1"
    openai_vision_key: str = ""
    openai_vision_model: str = "gpt-4o-mini"

    provider_order: tuple[str, ...] = ("gemini", "openai")
    timeout_s: int = 420
    reference_min: int = 3
    reference_max: int = 6
    max_attempts: int = 2
    min_user_similarity: int = 90
    min_character_similarity: int = 90
    min_quality: int = 72
    qc_enabled: bool = True
    page_size: int = 6
    cost_usd: float = 0.20


@dataclass(slots=True)
class ReferenceRecord:
    filename: str
    sha256: str
    width: int
    height: int
    created_at: float


@dataclass(slots=True)
class CharacterRecord:
    slug: str
    title: str
    aliases: list[str]
    active: bool
    refs: list[ReferenceRecord]
    created_by: int
    created_at: float
    updated_at: float


@dataclass(slots=True)
class QualityResult:
    user_similarity: int
    character_similarity: int
    quality: int
    exactly_two_people: bool
    no_face_merge: bool
    scene_match: bool
    notes: str = ""

    @property
    def total(self) -> int:
        return self.user_similarity + self.character_similarity + self.quality


class QualityGateError(RuntimeError):
    def __init__(self, message: str, result: Optional[QualityResult] = None):
        super().__init__(message)
        self.result = result


SCENES: dict[str, tuple[str, str]] = {
    "premiere": (
        "🎬 Премьера",
        "Photorealistic smartphone selfie at a film premiere, elegant evening clothes, premium event lighting, coherent red-carpet atmosphere.",
    ),
    "restaurant": (
        "🍽 Ресторан",
        "Photorealistic smartphone selfie in a stylish restaurant, warm realistic light, natural interaction, believable table and interior perspective.",
    ),
    "yacht": (
        "⛵ Яхта",
        "Photorealistic luxury yacht selfie, natural daylight, believable sea and deck perspective, subtle wind, premium travel atmosphere.",
    ),
    "exhibition": (
        "🏛 Выставка",
        "Photorealistic selfie at a modern exhibition or gallery, clean architecture, realistic indoor light, natural body poses.",
    ),
    "red_square": (
        "🏙 Красная площадь",
        "Photorealistic smartphone selfie on Red Square in Moscow, authentic urban environment, realistic daylight or evening city light.",
    ),
}


class CatalogStore:
    """Atomic JSON catalog plus persistent reference files."""

    def __init__(self, config: CelebritySelfieConfig):
        self.config = config
        self.root = Path(config.data_dir).expanduser().resolve()
        self.seed_root = Path(config.seed_dir).expanduser().resolve()
        self.catalog_path = self.root / "catalog.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._bootstrap_seed()

    def _bootstrap_seed(self) -> None:
        seed_catalog = self.seed_root / "catalog.json"
        if not self.catalog_path.exists():
            if seed_catalog.is_file():
                shutil.copy2(seed_catalog, self.catalog_path)
            else:
                self._write({"schema": 1, "characters": {}})
        if not seed_catalog.is_file():
            return
        try:
            current = self._read()
            seed = json.loads(seed_catalog.read_text(encoding="utf-8"))
            changed = False
            for slug, item in (seed.get("characters") or {}).items():
                if slug not in current["characters"]:
                    current["characters"][slug] = item
                    changed = True
                src_dir = self.seed_root / slug
                dst_dir = self.root / slug
                dst_dir.mkdir(parents=True, exist_ok=True)
                for ref in item.get("refs") or []:
                    filename = str(ref.get("filename") or "")
                    if not filename:
                        continue
                    src = src_dir / filename
                    dst = dst_dir / filename
                    if src.is_file() and not dst.exists():
                        shutil.copy2(src, dst)
            if changed:
                self._write(current)
        except Exception as exc:
            log.warning("seed merge failed: %s", exc)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("catalog root must be object")
            value.setdefault("schema", 1)
            value.setdefault("characters", {})
            return value
        except Exception:
            return {"schema": 1, "characters": {}}

    def _write(self, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.catalog_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.catalog_path)

    @staticmethod
    def slugify(title: str) -> str:
        translit = {
            "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
            "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
            "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
            "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
        }
        chars: list[str] = []
        for ch in (title or "").strip().lower():
            if ch in translit:
                chars.append(translit[ch])
            elif ch.isalnum():
                chars.append(ch)
            else:
                chars.append("-")
        slug = re.sub(r"-+", "-", "".join(chars)).strip("-")
        return slug or f"character-{int(time.time())}"

    @staticmethod
    def _aliases(title: str) -> list[str]:
        title = " ".join((title or "").casefold().replace("ё", "е").split())
        out = {title}
        parts = title.split()
        if len(parts) > 1:
            out.add(parts[-1])
        return sorted(x for x in out if x)

    @staticmethod
    def _record(slug: str, obj: dict[str, Any]) -> CharacterRecord:
        refs = [
            ReferenceRecord(
                filename=str(x.get("filename") or ""),
                sha256=str(x.get("sha256") or ""),
                width=int(x.get("width") or 0),
                height=int(x.get("height") or 0),
                created_at=float(x.get("created_at") or time.time()),
            )
            for x in (obj.get("refs") or [])
            if x.get("filename")
        ]
        return CharacterRecord(
            slug=slug,
            title=str(obj.get("title") or slug),
            aliases=list(obj.get("aliases") or []),
            active=bool(obj.get("active")),
            refs=refs,
            created_by=int(obj.get("created_by") or 0),
            created_at=float(obj.get("created_at") or time.time()),
            updated_at=float(obj.get("updated_at") or time.time()),
        )

    @staticmethod
    def _json_record(rec: CharacterRecord) -> dict[str, Any]:
        return {
            "title": rec.title,
            "aliases": rec.aliases,
            "active": rec.active,
            "created_by": rec.created_by,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
            "refs": [
                {
                    "filename": x.filename,
                    "sha256": x.sha256,
                    "width": x.width,
                    "height": x.height,
                    "created_at": x.created_at,
                }
                for x in rec.refs
            ],
        }

    def all(self) -> list[CharacterRecord]:
        data = self._read()["characters"]
        result = [self._record(slug, obj) for slug, obj in data.items()]
        return sorted(result, key=lambda x: x.title.casefold())

    def active(self) -> list[CharacterRecord]:
        return [x for x in self.all() if x.active and len(x.refs) >= self.config.reference_min]

    def get(self, slug: str) -> Optional[CharacterRecord]:
        obj = self._read()["characters"].get(slug)
        return self._record(slug, obj) if obj else None

    def create(self, title: str, user_id: int) -> CharacterRecord:
        title = " ".join((title or "").split()).strip()
        if len(title) < 2:
            raise ValueError("Имя слишком короткое")
        data = self._read()
        base = self.slugify(title)
        slug = base
        index = 2
        while slug in data["characters"]:
            slug = f"{base}-{index}"
            index += 1
        now = time.time()
        rec = CharacterRecord(slug, title, self._aliases(title), False, [], user_id, now, now)
        data["characters"][slug] = self._json_record(rec)
        self._write(data)
        (self.root / slug).mkdir(parents=True, exist_ok=True)
        return rec

    def save(self, rec: CharacterRecord) -> CharacterRecord:
        data = self._read()
        rec.updated_at = time.time()
        data["characters"][rec.slug] = self._json_record(rec)
        self._write(data)
        return rec

    def set_active(self, slug: str, active: bool) -> CharacterRecord:
        rec = self.get(slug)
        if not rec:
            raise KeyError(slug)
        if active and len(rec.refs) < self.config.reference_min:
            raise ValueError(f"Нужно минимум {self.config.reference_min} референса")
        rec.active = active
        return self.save(rec)

    def set_aliases(self, slug: str, aliases: Iterable[str]) -> CharacterRecord:
        rec = self.get(slug)
        if not rec:
            raise KeyError(slug)
        values = {" ".join(str(x).casefold().replace("ё", "е").split()) for x in aliases}
        values.add(" ".join(rec.title.casefold().replace("ё", "е").split()))
        rec.aliases = sorted(x for x in values if x)
        return self.save(rec)

    def clear_refs(self, slug: str) -> CharacterRecord:
        rec = self.get(slug)
        if not rec:
            raise KeyError(slug)
        directory = self.root / slug
        for ref in rec.refs:
            with contextlib.suppress(Exception):
                (directory / ref.filename).unlink()
        rec.refs = []
        rec.active = False
        return self.save(rec)

    def delete(self, slug: str) -> None:
        data = self._read()
        data["characters"].pop(slug, None)
        self._write(data)
        shutil.rmtree(self.root / slug, ignore_errors=True)

    def _normalise_image(self, raw: bytes) -> tuple[bytes, int, int]:
        if Image is None:
            raise RuntimeError("Pillow не установлен")
        image = Image.open(BytesIO(raw)).convert("RGB")
        width, height = image.size
        if min(width, height) < 320:
            raise ValueError("Фото слишком маленькое. Минимальная сторона — 320 px")
        if max(width, height) > 2200:
            image.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
        out = BytesIO()
        image.save(out, format="JPEG", quality=95, optimize=True)
        width, height = image.size
        return out.getvalue(), width, height

    def add_reference(self, slug: str, raw: bytes) -> CharacterRecord:
        rec = self.get(slug)
        if not rec:
            raise KeyError(slug)
        normalised, width, height = self._normalise_image(raw)
        digest = hashlib.sha256(normalised).hexdigest()
        if any(x.sha256 == digest for x in rec.refs):
            return rec
        if len(rec.refs) >= self.config.reference_max:
            raise ValueError(f"Максимум {self.config.reference_max} референсов")
        filename = f"ref_{len(rec.refs)+1:02d}.jpg"
        directory = self.root / slug
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_bytes(normalised)
        rec.refs.append(ReferenceRecord(filename, digest, width, height, time.time()))
        return self.save(rec)

    def ref_paths(self, slug: str) -> list[Path]:
        rec = self.get(slug)
        if not rec:
            return []
        directory = self.root / slug
        return [directory / x.filename for x in rec.refs if (directory / x.filename).is_file()]

    def search(self, query: str, active_only: bool = True) -> list[CharacterRecord]:
        q = " ".join((query or "").casefold().replace("ё", "е").split())
        source = self.active() if active_only else self.all()
        if not q:
            return source
        result = []
        for rec in source:
            fields = [rec.title.casefold(), rec.slug.casefold(), *[x.casefold() for x in rec.aliases]]
            if any(q in x or x in q for x in fields if x):
                result.append(rec)
        return result

    def match_in_text(self, text: str) -> Optional[CharacterRecord]:
        normalised = f" {' '.join((text or '').casefold().replace('ё', 'е').split())} "
        matches: list[tuple[int, CharacterRecord]] = []
        for rec in self.active():
            for alias in sorted({rec.title.casefold(), *rec.aliases}, key=len, reverse=True):
                alias = " ".join(alias.replace("ё", "е").split())
                if alias and f" {alias} " in normalised:
                    matches.append((len(alias), rec))
                    break
        return max(matches, key=lambda x: x[0])[1] if matches else None


class MultiReferenceRenderer:
    def __init__(self, config: CelebritySelfieConfig):
        self.config = config

    @staticmethod
    def _prepare(raw: bytes, max_side: int = 1536) -> bytes:
        if Image is None:
            return raw
        image = Image.open(BytesIO(raw)).convert("RGB")
        if max(image.size) > max_side:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = BytesIO()
        image.save(out, format="JPEG", quality=94, optimize=True)
        return out.getvalue()

    @staticmethod
    def _data_url(raw: bytes, mime: str = "image/jpeg") -> str:
        return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    def _prompt(self, character: CharacterRecord, scene: str, correction: str = "") -> str:
        correction_block = f"\nCORRECTION FROM PREVIOUS QC: {correction}" if correction else ""
        return (
            "Create one photorealistic AI-generated smartphone selfie scene with exactly two adults.\n"
            "IDENTITY A: the first input image is the user. Preserve the user's identity with maximum fidelity: facial geometry, age, "
            "hairline, eye spacing, nose, mouth, beard/makeup and skin tone.\n"
            f"IDENTITY B: all remaining reference images show the same person, {character.title}. Preserve this person's identity with maximum fidelity.\n"
            "Generate a completely new scene and new body poses. Both people may turn their heads and bodies naturally in any direction required by the scene. "
            "Do not copy the reference backgrounds. Keep both identities clearly separate.\n"
            "HARD RULES: exactly two adults; no third person; no face merge; no identity swap; no duplicate head; no wax figure; no collage; "
            "no split screen; no poster; no text; no logo; no watermark; realistic anatomy, hands, clothing, lighting and perspective.\n"
            "The image is fictional AI art and must not look like documentary proof or an official endorsement.\n"
            "Identity fidelity is more important than decorative style.\n"
            f"SCENE: {scene}.{correction_block}"
        )

    async def _gemini(self, user: bytes, refs: Sequence[bytes], prompt: str) -> bytes:
        if not self.config.gemini_api_key:
            raise RuntimeError("GEMINI_IMAGE_API_KEY отсутствует")
        models = [self.config.gemini_model, self.config.gemini_fallback_model]
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for raw in [user, *refs]:
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(raw).decode("ascii")}})
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "temperature": 0.2,
                "imageConfig": {"aspectRatio": "4:5", "imageSize": "2K"},
            },
        }
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=float(self.config.timeout_s), follow_redirects=True) as client:
            for model in models:
                if not model:
                    continue
                url = f"{self.config.gemini_base_url.rstrip('/')}/models/{model}:generateContent"
                try:
                    response = await client.post(url, params={"key": self.config.gemini_api_key}, json=payload)
                    if response.status_code >= 400:
                        errors.append(f"{model}: HTTP {response.status_code}: {response.text[:400]}")
                        continue
                    data = response.json() or {}
                    for candidate in data.get("candidates") or []:
                        for part in ((candidate.get("content") or {}).get("parts") or []):
                            inline = part.get("inlineData") or part.get("inline_data") or {}
                            encoded = inline.get("data")
                            if encoded:
                                return base64.b64decode(encoded)
                    errors.append(f"{model}: image part missing")
                except Exception as exc:
                    errors.append(f"{model}: {type(exc).__name__}: {exc}")
        raise RuntimeError(" | ".join(errors[-3:]) or "Gemini generation failed")

    async def _openai(self, user: bytes, refs: Sequence[bytes], prompt: str) -> bytes:
        key = self.config.openai_image_key
        if not key or key.startswith("sk-or-"):
            raise RuntimeError("официальный OPENAI_IMAGE_KEY отсутствует")
        headers = {"Authorization": f"Bearer {key}"}
        files = [("image[]", (f"input_{idx}.jpg", raw, "image/jpeg")) for idx, raw in enumerate([user, *refs], 1)]
        data = {
            "model": self.config.openai_image_model,
            "prompt": prompt,
            "n": "1",
            "size": "1024x1536",
            "input_fidelity": "high",
            "quality": "high",
        }
        async with httpx.AsyncClient(timeout=float(self.config.timeout_s), follow_redirects=True) as client:
            response = await client.post(
                f"{self.config.openai_base_url.rstrip('/')}/images/edits",
                headers=headers,
                data=data,
                files=files,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"OpenAI HTTP {response.status_code}: {response.text[:600]}")
            item = ((response.json() or {}).get("data") or [{}])[0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            if item.get("url"):
                result = await client.get(item["url"])
                result.raise_for_status()
                return result.content
            raise RuntimeError("OpenAI response has no image")

    def _reference_sheet(self, refs: Sequence[bytes]) -> bytes:
        if Image is None:
            return refs[0]
        tile = 512
        selected = list(refs[:4])
        canvas = Image.new("RGB", (tile * 2, tile * 2), "white")
        for index in range(4):
            if index >= len(selected):
                break
            image = Image.open(BytesIO(selected[index])).convert("RGB")
            image.thumbnail((tile, tile), Image.Resampling.LANCZOS)
            x = (index % 2) * tile + (tile - image.width) // 2
            y = (index // 2) * tile + (tile - image.height) // 2
            canvas.paste(image, (x, y))
        out = BytesIO()
        canvas.save(out, format="JPEG", quality=92)
        return out.getvalue()

    async def _qc(self, user: bytes, refs: Sequence[bytes], candidate: bytes, character: CharacterRecord, scene: str) -> QualityResult:
        if not self.config.qc_enabled:
            return QualityResult(100, 100, 100, True, True, True, "QC disabled")
        key = self.config.openai_vision_key
        if not key or key.startswith("sk-or-"):
            raise RuntimeError("Для строгого QC требуется официальный OPENAI_API_KEY/OPENAI_IMAGE_KEY")
        sheet = self._reference_sheet(refs)
        prompt = (
            "You are a strict biometric-style visual quality auditor. Do not identify unknown people by name. "
            "Compare identity A reference, identity B reference sheet, and the generated candidate. Return only JSON with integer scores 0-100 and booleans. "
            "user_similarity: how closely the left/reference user identity is preserved. character_similarity: how closely identity B is preserved. "
            "quality: anatomy, realism, hands, lighting, perspective. exactly_two_people: candidate contains exactly two main adults. "
            "no_face_merge: identities are separate and not blended. scene_match: candidate follows the requested scene. "
            "notes: short technical correction. Be conservative; 90 means highly convincing identity preservation.\n"
            f"Character label for bookkeeping only: {character.title}. Requested scene: {scene}."
        )
        payload = {
            "model": self.config.openai_vision_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": self._data_url(user)}},
                    {"type": "image_url", "image_url": {"url": self._data_url(sheet)}},
                    {"type": "image_url", "image_url": {"url": self._data_url(candidate)}},
                ],
            }],
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.config.openai_base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
            if response.status_code >= 400:
                raise RuntimeError(f"QC HTTP {response.status_code}: {response.text[:500]}")
            text = (((response.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        match = re.search(r"\{.*\}", text, re.S)
        obj = json.loads(match.group(0) if match else text)
        return QualityResult(
            user_similarity=max(0, min(100, int(obj.get("user_similarity") or 0))),
            character_similarity=max(0, min(100, int(obj.get("character_similarity") or 0))),
            quality=max(0, min(100, int(obj.get("quality") or 0))),
            exactly_two_people=bool(obj.get("exactly_two_people")),
            no_face_merge=bool(obj.get("no_face_merge")),
            scene_match=bool(obj.get("scene_match")),
            notes=str(obj.get("notes") or "")[:500],
        )

    def _passes(self, result: QualityResult) -> bool:
        return (
            result.user_similarity >= self.config.min_user_similarity
            and result.character_similarity >= self.config.min_character_similarity
            and result.quality >= self.config.min_quality
            and result.exactly_two_people
            and result.no_face_merge
            and result.scene_match
        )

    async def render(self, user_raw: bytes, ref_raws: Sequence[bytes], character: CharacterRecord, scene: str) -> tuple[bytes, QualityResult, str]:
        user = self._prepare(user_raw)
        refs = [self._prepare(x) for x in ref_raws[: self.config.reference_max]]
        if len(refs) < self.config.reference_min:
            raise RuntimeError(f"Недостаточно референсов персонажа: {len(refs)}/{self.config.reference_min}")
        best: Optional[tuple[bytes, QualityResult, str]] = None
        correction = ""
        errors: list[str] = []
        for attempt in range(1, self.config.max_attempts + 1):
            prompt = self._prompt(character, scene, correction)
            for provider in self.config.provider_order:
                try:
                    if provider == "gemini":
                        candidate = await self._gemini(user, refs, prompt)
                    elif provider == "openai":
                        candidate = await self._openai(user, refs, prompt)
                    else:
                        continue
                    result = await self._qc(user, refs, candidate, character, scene)
                    if best is None or result.total > best[1].total:
                        best = (candidate, result, provider)
                    if self._passes(result):
                        return candidate, result, provider
                    correction = result.notes or (
                        f"Increase identity fidelity. User score {result.user_similarity}; second identity score {result.character_similarity}; "
                        f"quality {result.quality}. Keep exactly two separate people."
                    )
                except Exception as exc:
                    errors.append(f"attempt {attempt}/{provider}: {type(exc).__name__}: {exc}")
                    log.warning("selfie render attempt failed: %s", errors[-1])
        if best:
            result = best[1]
            raise QualityGateError(
                f"QC не пропустил результат: пользователь {result.user_similarity}/100, персонаж {result.character_similarity}/100, качество {result.quality}/100",
                result,
            )
        raise RuntimeError(" | ".join(errors[-5:]) or "Провайдер не вернул изображение")


class CelebritySelfieFeature:
    FLOW_KEY = "celebrity_selfie_clean_flow"
    ADMIN_KEY = "celebrity_selfie_clean_admin"
    LAST_FILE_KEY = "celebrity_selfie_clean_last_file"

    def __init__(
        self,
        config: CelebritySelfieConfig,
        charge_and_run: Optional[ChargeAndRun] = None,
        get_cached_photo: Optional[GetCachedPhoto] = None,
        cache_photo: Optional[CachePhoto] = None,
    ):
        self.config = config
        self.store = CatalogStore(config)
        self.renderer = MultiReferenceRenderer(config)
        self.charge_and_run = charge_and_run
        self.get_cached_photo = get_cached_photo
        self.cache_photo = cache_photo

    def version_lines(self) -> list[str]:
        return [
            "celebrity_selfie_flow=clean-state-machine-v200",
            "celebrity_selfie_admin=hidden-dynamic-catalog",
            "celebrity_selfie_renderer=dual-identity-multi-reference",
            f"celebrity_selfie_providers={','.join(self.config.provider_order)}",
            f"celebrity_selfie_refs={self.config.reference_min}-{self.config.reference_max}",
            f"celebrity_selfie_attempts={self.config.max_attempts}",
            f"celebrity_selfie_qc=user>={self.config.min_user_similarity},character>={self.config.min_character_similarity},quality>={self.config.min_quality}",
            f"celebrity_selfie_data_dir={self.config.data_dir}",
        ]

    def handlers(self) -> list[Any]:
        image_filter = filters.PHOTO
        with contextlib.suppress(Exception):
            image_filter = image_filter | filters.Document.IMAGE
        return [
            CommandHandler(self.config.hidden_admin_command, self.admin_command),
            CallbackQueryHandler(
                self.callback,
                pattern=r"^(?:cs2:|csa2:|act:fun:aiselfie(?:.*)?$|fun:aiselfie(?:.*)?$|pedit:aiselfie(?:.*)?$)",
            ),
            MessageHandler(image_filter, self.image_message),
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_message),
        ]

    def _flow(self, context: ContextTypes.DEFAULT_TYPE, create: bool = True) -> Optional[dict[str, Any]]:
        value = context.user_data.get(self.FLOW_KEY)
        if isinstance(value, dict):
            created_at = float(value.get("created_at") or 0.0)
            if created_at and time.time() - created_at > 7200:
                context.user_data.pop(self.FLOW_KEY, None)
                value = None
        if create:
            return context.user_data.setdefault(self.FLOW_KEY, {})
        return value if isinstance(value, dict) else None

    def _admin(self, context: ContextTypes.DEFAULT_TYPE, create: bool = True) -> Optional[dict[str, Any]]:
        if create:
            return context.user_data.setdefault(self.ADMIN_KEY, {})
        value = context.user_data.get(self.ADMIN_KEY)
        return value if isinstance(value, dict) else None

    def _is_admin(self, update: Update) -> bool:
        return bool(update.effective_user and update.effective_user.id in self.config.admin_ids)

    @staticmethod
    def _kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows])

    def entry_kb(self) -> InlineKeyboardMarkup:
        return self._kb([
            [("📷 Загрузить своё селфи", "cs2:upload")],
            [("✅ Использовать последнее фото", "cs2:last")],
            [("❌ Отмена", "cs2:cancel")],
        ])

    def scene_kb(self) -> InlineKeyboardMarkup:
        return self._kb([
            [(SCENES["premiere"][0], "cs2:scene:premiere"), (SCENES["restaurant"][0], "cs2:scene:restaurant")],
            [(SCENES["yacht"][0], "cs2:scene:yacht"), (SCENES["exhibition"][0], "cs2:scene:exhibition")],
            [(SCENES["red_square"][0], "cs2:scene:red_square")],
            [("📝 Своя сцена", "cs2:scene:custom")],
            [("⭐ Сменить знаменитость", "cs2:change")],
            [("❌ Отмена", "cs2:cancel")],
        ])

    def catalog_kb(self, page: int = 0, items: Optional[list[CharacterRecord]] = None) -> InlineKeyboardMarkup:
        items = items if items is not None else self.store.active()
        size = max(1, self.config.page_size)
        pages = max(1, (len(items) + size - 1) // size)
        page = max(0, min(page, pages - 1))
        rows = [[(x.title, f"cs2:pick:{x.slug}")] for x in items[page * size:(page + 1) * size]]
        nav: list[tuple[str, str]] = []
        if page > 0:
            nav.append(("⬅️", f"cs2:page:{page-1}"))
        nav.append((f"{page+1}/{pages}", "cs2:noop"))
        if page + 1 < pages:
            nav.append(("➡️", f"cs2:page:{page+1}"))
        rows.append(nav)
        rows.append([("🔎 Поиск", "cs2:search")])
        rows.append([("❌ Отмена", "cs2:cancel")])
        return self._kb(rows)

    def retry_kb(self) -> InlineKeyboardMarkup:
        return self._kb([
            [("🔁 Повторить", "cs2:retry")],
            [("⭐ Сменить знаменитость", "cs2:change"), ("📝 Сменить сцену", "cs2:scene:custom")],
            [("❌ Отмена", "cs2:cancel")],
        ])

    def admin_menu_kb(self) -> InlineKeyboardMarkup:
        return self._kb([
            [("➕ Создать персонажа", "csa2:create")],
            [("👥 Каталог персонажей", "csa2:list:0")],
            [("❌ Закрыть", "csa2:close")],
        ])

    def admin_card_kb(self, rec: CharacterRecord) -> InlineKeyboardMarkup:
        publish = ("⛔ Снять с публикации", f"csa2:disable:{rec.slug}") if rec.active else ("✅ Опубликовать", f"csa2:publish:{rec.slug}")
        return self._kb([
            [("📥 Добавить фото", f"csa2:upload:{rec.slug}"), ("🧹 Очистить фото", f"csa2:clear:{rec.slug}")],
            [("✏️ Алиасы", f"csa2:aliases:{rec.slug}")],
            [publish],
            [("🗑 Удалить персонажа", f"csa2:delete_ask:{rec.slug}")],
            [("⬅️ В админку", "csa2:menu")],
        ])

    def admin_list_kb(self, page: int = 0) -> InlineKeyboardMarkup:
        items = self.store.all()
        size = 8
        pages = max(1, (len(items) + size - 1) // size)
        page = max(0, min(page, pages - 1))
        rows = [[(("✅" if x.active else "📝") + f" {x.title} · {len(x.refs)} фото", f"csa2:view:{x.slug}")] for x in items[page * size:(page + 1) * size]]
        nav: list[tuple[str, str]] = []
        if page > 0:
            nav.append(("⬅️", f"csa2:list:{page-1}"))
        nav.append((f"{page+1}/{pages}", "csa2:noop"))
        if page + 1 < pages:
            nav.append(("➡️", f"csa2:list:{page+1}"))
        rows.append(nav)
        rows.append([("⬅️ В админку", "csa2:menu")])
        return self._kb(rows)

    async def open(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.config.enabled:
            await update.effective_message.reply_text("⚠️ Режим «AI-селфи со звездой» временно отключён.")
            return
        context.user_data.pop(self.FLOW_KEY, None)
        self._flow(context).update({"step": "await_selfie", "created_at": time.time()})
        await update.effective_message.reply_text(
            "🤳 AI-селфи со звездой\n\n"
            "1. Загрузите своё селфи.\n"
            "2. Выберите знаменитость из каталога.\n"
            "3. Выберите или опишите сцену.\n\n"
            "Сцена создаётся заново по двум наборам идентичности, поэтому оба человека могут быть в любом естественном повороте и позе. "
            "Результат проходит строгую проверку сходства перед отправкой.",
            reply_markup=self.entry_kb(),
        )

    async def callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        data = str(query.data or "")
        with contextlib.suppress(Exception):
            await query.answer()
        if data.startswith("act:fun:aiselfie") or data.startswith("fun:aiselfie") or data.startswith("pedit:aiselfie"):
            await self.open(update, context)
            raise ApplicationHandlerStop
        if data in {"cs2:noop", "csa2:noop"}:
            raise ApplicationHandlerStop
        if data.startswith("csa2:"):
            await self._admin_callback(update, context, data)
            raise ApplicationHandlerStop
        await self._public_callback(update, context, data)
        raise ApplicationHandlerStop

    async def _public_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
        message = update.effective_message
        flow = self._flow(context)
        if data == "cs2:upload":
            flow.clear(); flow.update({"step": "await_selfie", "created_at": time.time()})
            await message.reply_text("📷 Пришлите своё селфи фотографией или файлом JPG/PNG/WEBP.")
            return
        if data == "cs2:last":
            raw = self.get_cached_photo(update.effective_user.id) if self.get_cached_photo else None
            if not raw:
                await message.reply_text("Последнее фото не найдено. Пришлите новое селфи.")
                return
            flow.clear(); flow.update({"step": "await_target", "selfie_bytes": raw, "created_at": time.time()})
            await message.reply_text("✅ Использую последнее фото. Теперь выберите знаменитость.", reply_markup=self.catalog_kb())
            return
        if data == "cs2:cancel":
            context.user_data.pop(self.FLOW_KEY, None)
            await message.reply_text("❌ Режим AI-селфи отменён.")
            return
        if not flow:
            await self.open(update, context)
            return
        if data.startswith("cs2:page:"):
            await message.reply_text("⭐ Выберите знаменитость.", reply_markup=self.catalog_kb(int(data.rsplit(":", 1)[-1])))
            return
        if data == "cs2:search":
            flow["step"] = "await_search"
            await message.reply_text("🔎 Напишите имя или фамилию персонажа.")
            return
        if data == "cs2:change":
            if not self._has_selfie(flow):
                flow["step"] = "await_selfie"
                await message.reply_text("Сначала загрузите селфи.", reply_markup=self.entry_kb())
            else:
                flow["step"] = "await_target"
                await message.reply_text("⭐ Выберите знаменитость.", reply_markup=self.catalog_kb())
            return
        if data.startswith("cs2:pick:"):
            rec = self.store.get(data.split(":", 2)[-1])
            if not rec or not rec.active:
                await message.reply_text("Персонаж недоступен.")
                return
            if not self._has_selfie(flow):
                flow["step"] = "await_selfie"
                await message.reply_text("Сначала загрузите селфи.", reply_markup=self.entry_kb())
                return
            flow.update({"target_slug": rec.slug, "target_title": rec.title, "step": "await_scene"})
            pending = str(flow.pop("pending_scene", "") or "").strip()
            if pending:
                flow["scene"] = pending
                await self._render(update, context)
            else:
                await message.reply_text(f"✅ Выбран: {rec.title}. Теперь выберите сцену.", reply_markup=self.scene_kb())
            return
        if data.startswith("cs2:scene:"):
            if not flow.get("target_slug"):
                flow["step"] = "await_target"
                await message.reply_text("Сначала выберите знаменитость.", reply_markup=self.catalog_kb())
                return
            key = data.split(":", 2)[-1]
            if key == "custom":
                flow["step"] = "await_scene_text"
                await message.reply_text("📝 Опишите сцену одним сообщением.")
                return
            if key not in SCENES:
                await message.reply_text("Неизвестная сцена.")
                return
            flow["scene"] = SCENES[key][1]
            await self._render(update, context)
            return
        if data == "cs2:retry":
            await self._render(update, context)

    async def text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message or not message.text:
            return
        text = message.text.strip()
        if self._is_admin(update) and await self._admin_text(update, context, text):
            raise ApplicationHandlerStop
        flow = self._flow(context, create=False)
        if flow:
            await self._flow_text(update, context, flow, text)
            raise ApplicationHandlerStop
        if text == self.config.public_button_text or self._looks_like_selfie_request(text):
            await self._start_from_free_text(update, context, text)
            raise ApplicationHandlerStop

    @staticmethod
    def _looks_like_selfie_request(text: str) -> bool:
        return bool(re.search(r"(?:ai[-\s]?селфи|аи[-\s]?селфи|селфи|selfie|фото\s+(?:с|со)\s+)", text or "", re.I))

    def _extract_scene(self, text: str, rec: Optional[CharacterRecord]) -> str:
        value = " ".join((text or "").split())
        patterns = [r"\b(?:сделай|создай|сгенерируй|хочу|нужно|пожалуйста)\b", r"\b(?:ai[-\s]?селфи|аи[-\s]?селфи|селфи|selfie|фото)\b"]
        for pattern in patterns:
            value = re.sub(pattern, " ", value, flags=re.I)
        if rec:
            for alias in sorted({rec.title, *rec.aliases}, key=len, reverse=True):
                value = re.sub(re.escape(alias), " ", value, flags=re.I)
        value = re.sub(r"\b(?:с|со|вместе\s+с)\b", " ", value, flags=re.I)
        return re.sub(r"\s+", " ", value).strip(" ,.-")

    async def _start_from_free_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        context.user_data.pop(self.FLOW_KEY, None)
        flow = self._flow(context)
        rec = self.store.match_in_text(text)
        scene = self._extract_scene(text, rec)
        raw = self.get_cached_photo(update.effective_user.id) if self.get_cached_photo else None
        flow.update({"created_at": time.time(), "pending_scene": scene})
        if rec:
            flow.update({"target_slug": rec.slug, "target_title": rec.title})
        if not raw:
            flow["step"] = "await_selfie"
            await update.effective_message.reply_text(
                "📷 Запрос сохранён. Теперь пришлите своё селфи. После загрузки я подтвержу персонажа и сцену.",
                reply_markup=self.entry_kb(),
            )
            return
        flow["selfie_bytes"] = raw
        if not rec:
            flow["step"] = "await_target"
            await update.effective_message.reply_text(
                "Сцена понятна, но не выбран человек. Выберите знаменитость.",
                reply_markup=self.catalog_kb(),
            )
            return
        if not scene:
            flow["step"] = "await_scene"
            await update.effective_message.reply_text(f"✅ Выбран: {rec.title}. Теперь выберите сцену.", reply_markup=self.scene_kb())
            return
        flow["scene"] = scene
        await self._render(update, context)

    async def _flow_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, flow: dict[str, Any], text: str) -> None:
        step = flow.get("step")
        if step in {"await_target", "await_search"}:
            matches = self.store.search(text)
            if len(matches) == 1:
                rec = matches[0]
                flow.update({"target_slug": rec.slug, "target_title": rec.title})
                pending = str(flow.pop("pending_scene", "") or "").strip()
                if pending:
                    flow["scene"] = pending
                    await self._render(update, context)
                else:
                    flow["step"] = "await_scene"
                    await update.effective_message.reply_text(f"✅ Выбран: {rec.title}. Теперь выберите сцену.", reply_markup=self.scene_kb())
            else:
                await update.effective_message.reply_text("Не удалось однозначно выбрать персонажа.", reply_markup=self.catalog_kb(items=matches or None))
            return
        if step in {"await_scene", "await_scene_text"}:
            if not flow.get("target_slug"):
                flow["step"] = "await_target"
                await update.effective_message.reply_text("Сначала выберите знаменитость.", reply_markup=self.catalog_kb())
                return
            flow["scene"] = text
            await self._render(update, context)
            return
        if step == "await_selfie":
            await update.effective_message.reply_text("Пришлите именно фотографию селфи.")

    async def image_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if not message:
            return
        file_id = ""
        filename = "image.jpg"
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.document and str(message.document.mime_type or "").startswith("image/"):
            file_id = message.document.file_id
            filename = message.document.file_name or filename
        if not file_id:
            return
        tg_file = await context.bot.get_file(file_id)
        raw = bytes(await tg_file.download_as_bytearray())
        if self.cache_photo and update.effective_user:
            with contextlib.suppress(Exception):
                self.cache_photo(update.effective_user.id, raw, str(getattr(tg_file, "file_path", "") or ""))
        context.user_data[self.LAST_FILE_KEY] = file_id

        admin = self._admin(context, create=False)
        if admin and admin.get("step") == "await_refs" and self._is_admin(update):
            try:
                rec = self.store.add_reference(str(admin.get("slug")), raw)
                await message.reply_text(
                    f"✅ Фото добавлено: {rec.title}. Набор: {len(rec.refs)}/{self.config.reference_max}.",
                    reply_markup=self.admin_card_kb(rec),
                )
            except Exception as exc:
                await message.reply_text(f"⚠️ Фото не добавлено: {exc}")
            raise ApplicationHandlerStop

        flow = self._flow(context, create=False)
        active_steps = {"await_selfie", "await_target", "await_search", "await_scene", "await_scene_text"}
        if flow and flow.get("step") in active_steps:
            flow["selfie_file_id"] = file_id
            flow["step"] = "await_target"
            if flow.get("target_slug"):
                pending = str(flow.pop("pending_scene", "") or "").strip()
                if pending:
                    flow["scene"] = pending
                    await self._render(update, context)
                else:
                    flow["step"] = "await_scene"
                    await message.reply_text(f"✅ Селфи получено. Выбран: {flow.get('target_title')}. Теперь выберите сцену.", reply_markup=self.scene_kb())
            else:
                await message.reply_text("✅ Селфи получено. Теперь выберите знаменитость.", reply_markup=self.catalog_kb())
            raise ApplicationHandlerStop

    def _has_selfie(self, flow: dict[str, Any]) -> bool:
        return bool(flow.get("selfie_bytes") or flow.get("selfie_file_id"))

    async def _selfie_bytes(self, update: Update, context: ContextTypes.DEFAULT_TYPE, flow: dict[str, Any]) -> bytes:
        if flow.get("selfie_bytes"):
            return bytes(flow["selfie_bytes"])
        file_id = str(flow.get("selfie_file_id") or "")
        if not file_id:
            raise RuntimeError("Селфи не найдено")
        tg_file = await context.bot.get_file(file_id)
        return bytes(await tg_file.download_as_bytearray())

    async def _render(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        flow = self._flow(context)
        message = update.effective_message
        slug = str(flow.get("target_slug") or "")
        scene = str(flow.get("scene") or "").strip()
        rec = self.store.get(slug)
        if not self._has_selfie(flow):
            flow["step"] = "await_selfie"
            await message.reply_text("Сначала загрузите селфи.", reply_markup=self.entry_kb())
            return
        if not rec or not rec.active:
            flow["step"] = "await_target"
            await message.reply_text("Сначала выберите доступного персонажа.", reply_markup=self.catalog_kb())
            return
        if not scene:
            flow["step"] = "await_scene"
            await message.reply_text("Сначала выберите сцену.", reply_markup=self.scene_kb())
            return

        async def work() -> bool:
            try:
                await message.reply_text(
                    f"⏳ Создаю новую сцену с {rec.title}. Проверяю сходство обоих лиц; слабый результат пользователю не отправляется."
                )
                with contextlib.suppress(Exception):
                    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
                user_raw = await self._selfie_bytes(update, context, flow)
                ref_raws = [path.read_bytes() for path in self.store.ref_paths(rec.slug)]
                output, qc, provider = await self.renderer.render(user_raw, ref_raws, rec, scene)
                result = BytesIO(output)
                result.name = f"ai_selfie_{rec.slug}.png"
                caption = (
                    f"✅ AI-селфи готово: {rec.title}.\n"
                    f"QC: пользователь {qc.user_similarity}/100 · персонаж {qc.character_similarity}/100 · качество {qc.quality}/100 · {provider}.\n"
                    "Изображение создано ИИ и не является доказательством реальной встречи или поддержки."
                )
                await message.reply_document(document=InputFile(result), caption=caption)
                flow["step"] = "await_scene"
                return True
            except Exception as exc:
                code = hashlib.sha1(f"{time.time()}::{exc}".encode()).hexdigest()[:12]
                log.exception("celebrity selfie failed code=%s", code)
                flow["step"] = "await_scene"
                await message.reply_text(
                    f"❌ Качественный результат не получен, изображение не отправлено.\n{exc}\nКод: {code}.\nКредиты за невыданный результат не должны списываться.",
                    reply_markup=self.retry_kb(),
                )
                return False

        if self.charge_and_run:
            await self.charge_and_run(update, context, "img", self.config.cost_usd, work)
        else:
            await work()

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_admin(update):
            await update.effective_message.reply_text("⛔ Команда недоступна.")
            return
        context.user_data.pop(self.ADMIN_KEY, None)
        await update.effective_message.reply_text("⚙️ Скрытая админка персонажей", reply_markup=self.admin_menu_kb())

    def _admin_summary(self, rec: CharacterRecord) -> str:
        refs = "\n".join(f"• {x.filename}: {x.width}×{x.height}, SHA-256 {x.sha256[:12]}…" for x in rec.refs) or "• нет"
        return (
            f"👤 {rec.title}\nslug: {rec.slug}\nстатус: {'опубликован' if rec.active else 'черновик'}\n"
            f"алиасы: {', '.join(rec.aliases)}\nреференсы:\n{refs}\n"
            f"Для публикации нужно минимум {self.config.reference_min}."
        )

    async def _admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
        message = update.effective_message
        if not self._is_admin(update):
            await message.reply_text("⛔ Недостаточно прав.")
            return
        if data == "csa2:menu":
            context.user_data.pop(self.ADMIN_KEY, None)
            await message.reply_text("⚙️ Скрытая админка персонажей", reply_markup=self.admin_menu_kb())
            return
        if data == "csa2:close":
            context.user_data.pop(self.ADMIN_KEY, None)
            await message.reply_text("Админка закрыта.")
            return
        if data == "csa2:create":
            self._admin(context).clear(); self._admin(context)["step"] = "await_name"
            await message.reply_text("Введите имя нового персонажа.")
            return
        if data.startswith("csa2:list:"):
            await message.reply_text("Каталог персонажей", reply_markup=self.admin_list_kb(int(data.rsplit(":", 1)[-1])))
            return
        if data.startswith("csa2:view:"):
            rec = self.store.get(data.split(":", 2)[-1])
            if rec:
                await message.reply_text(self._admin_summary(rec), reply_markup=self.admin_card_kb(rec))
            return
        if data.startswith("csa2:upload:"):
            slug = data.split(":", 2)[-1]
            rec = self.store.get(slug)
            if not rec:
                return
            self._admin(context).clear(); self._admin(context).update({"step": "await_refs", "slug": slug})
            await message.reply_text(f"📥 Загружайте фотографии для {rec.title}. Максимум {self.config.reference_max}.")
            return
        if data.startswith("csa2:aliases:"):
            slug = data.split(":", 2)[-1]
            self._admin(context).clear(); self._admin(context).update({"step": "await_aliases", "slug": slug})
            await message.reply_text("Введите алиасы через запятую.")
            return
        if data.startswith("csa2:clear:"):
            rec = self.store.clear_refs(data.split(":", 2)[-1])
            await message.reply_text("🧹 Референсы удалены. Персонаж снят с публикации.", reply_markup=self.admin_card_kb(rec))
            return
        if data.startswith("csa2:publish:"):
            try:
                rec = self.store.set_active(data.split(":", 2)[-1], True)
                await message.reply_text(f"✅ {rec.title} опубликован и появился в публичном меню.", reply_markup=self.admin_card_kb(rec))
            except Exception as exc:
                await message.reply_text(f"Не удалось опубликовать: {exc}")
            return
        if data.startswith("csa2:disable:"):
            rec = self.store.set_active(data.split(":", 2)[-1], False)
            await message.reply_text(f"⛔ {rec.title} снят с публикации.", reply_markup=self.admin_card_kb(rec))
            return
        if data.startswith("csa2:delete_ask:"):
            slug = data.split(":", 2)[-1]
            await message.reply_text("Удалить персонажа и все его фотографии?", reply_markup=self._kb([[("Да, удалить", f"csa2:delete:{slug}")], [("Отмена", f"csa2:view:{slug}")]]))
            return
        if data.startswith("csa2:delete:"):
            slug = data.split(":", 2)[-1]
            self.store.delete(slug)
            context.user_data.pop(self.ADMIN_KEY, None)
            await message.reply_text("🗑 Персонаж удалён.", reply_markup=self.admin_menu_kb())

    async def _admin_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
        state = self._admin(context, create=False)
        if not state:
            return False
        step = state.get("step")
        if step == "await_name":
            try:
                rec = self.store.create(text, update.effective_user.id)
            except Exception as exc:
                await update.effective_message.reply_text(f"Не удалось создать: {exc}")
                return True
            state.clear(); state.update({"step": "await_refs", "slug": rec.slug})
            await update.effective_message.reply_text(
                f"✅ Создан черновик: {rec.title}. Теперь загрузите {self.config.reference_min}-{self.config.reference_max} фотографий.",
                reply_markup=self.admin_card_kb(rec),
            )
            return True
        if step == "await_aliases":
            rec = self.store.set_aliases(str(state.get("slug")), [x.strip() for x in text.split(",") if x.strip()])
            state.clear()
            await update.effective_message.reply_text("✅ Алиасы обновлены.", reply_markup=self.admin_card_kb(rec))
            return True
        return False


def parse_admin_ids(owner_id: int = 0) -> set[int]:
    result = {int(owner_id)} if int(owner_id or 0) > 0 else set()
    for value in re.split(r"[,;\s]+", os.environ.get("CELEBRITY_SELFIE_ADMIN_IDS", "")):
        with contextlib.suppress(Exception):
            if int(value) > 0:
                result.add(int(value))
    return result


__all__ = [
    "VERSION",
    "CelebritySelfieConfig",
    "CelebritySelfieFeature",
    "CatalogStore",
    "CharacterRecord",
    "QualityResult",
    "parse_admin_ids",
]
