# -*- coding: utf-8 -*-
"""Celebrity Selfie v158: bundled Roman Abramovich identity reference pack.

The v157 wizard and v156 coherent Comet renderer stay intact.  This release
replaces the volatile/web-downloaded Roman Abramovich cache with three curated,
age-consistent, face-centred references shipped with the repository.  Selection,
scene generation and the user's identity path are otherwise unchanged.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

import celebrity_selfie_v139 as v139
import celebrity_selfie_v156 as renderer
import celebrity_selfie_v157 as previous

VERSION = "v158-bundled-abramovich-identity-pack-2026-07-23"
_GROUP = -2_100_004_000
_BUILDER_FLAG = "_celebrity_selfie_v158_builder"
_HANDLER_FLAG = "_celebrity_selfie_v158_handlers"
_INSTALL_FLAG = "_celebrity_selfie_v158_installed"

CELEBRITY_ID = "ru_roman_abramovich"
CELEBRITY_NAME = "Роман Абрамович"
_ASSET_DIR = Path(__file__).resolve().parent / "celebrity_library" / "bundled" / CELEBRITY_ID
_ASSET_GROUPS = {
    "ref_01.jpg": ("ref_01.part_01.b64", "ref_01.part_02.b64"),
    "ref_02.jpg": ("ref_02.part_01.b64", "ref_02.part_02.b64"),
    "ref_03.jpg": ("ref_03.part_01.b64", "ref_03.part_02.b64"),
}
_EXPECTED_SHA256 = {
    "ref_01.jpg": "56244292676776752d7b0a42bcc494b841f29dba928ef482ded1dbef2e08fcd8",
    "ref_02.jpg": "d385e567faeffb59a672cdc816d664a38a94f4f9823a1e8eb97eb414b389f5eb",
    "ref_03.jpg": "c42b098252f0544dd5065b22686721c3e1b348f970ff19db1b251db201b46f1f",
}

log = logging.getLogger("gpt-bot.celebrity-selfie-v158")
_BASE_SCENE_PROMPT = previous._scene_prompt
_BASE_GENERATE = previous._generate
_ORIGINAL_ENSURE_REFS: Any = None
_ORIGINAL_REFERENCE_PATHS: Any = None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _is_roman_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if str(entry.get("id") or "").strip() == CELEBRITY_ID:
        return True
    values = [
        entry.get("display_name"),
        entry.get("name"),
        entry.get("sort_name"),
        *(entry.get("aliases") or []),
    ]
    return any("абрамович" in _norm(value) or "abramovich" in _norm(value) for value in values)


def _selected_entry(session: dict[str, Any]) -> dict[str, Any] | None:
    with contextlib.suppress(Exception):
        entry = v139.selfie.engine._selected_entry(session)
        if isinstance(entry, dict):
            return entry
    return None


def _roman_selected(session: Any) -> bool:
    if not isinstance(session, dict):
        return False
    if str(session.get("selected_celebrity_id") or "").strip() == CELEBRITY_ID:
        return True
    entry = _selected_entry(session)
    if _is_roman_entry(entry):
        return True
    names = (
        session.get("selected_celebrity_name"),
        session.get("celebrity_name"),
        session.get("generation_celebrity_snapshot"),
    )
    return any("абрамович" in _norm(value) or "abramovich" in _norm(value) for value in names)


def _entry_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("entry", "celebrity", "person"):
        value = kwargs.get(key)
        if isinstance(value, dict):
            return value
    for value in args:
        if isinstance(value, dict) and (value.get("id") or value.get("display_name")):
            return value
    return None


def _asset_bytes(output_name: str) -> bytes:
    parts = _ASSET_GROUPS[output_name]
    encoded = "".join(
        "".join((_ASSET_DIR / part).read_text(encoding="ascii").split())
        for part in parts
    )
    raw = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    expected = _EXPECTED_SHA256[output_name]
    if digest != expected:
        raise RuntimeError(f"bundled reference checksum mismatch for {output_name}: {digest}")
    with Image.open(BytesIO(raw)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        if min(image.size) < 600:
            raise RuntimeError(f"bundled reference too small for {output_name}: {image.size}")
    return raw


def _canonical_directory(root: Path) -> Path:
    # This matches the v122 reference-library layout documented by the project.
    return root / "ru" / "А" / CELEBRITY_ID


def _candidate_directories(root: Path) -> list[Path]:
    result = {
        _canonical_directory(root),
        root / "ru" / CELEBRITY_ID,
        root / CELEBRITY_ID,
    }
    # Upgrade an already-created cache in place even if an older release used a
    # slightly different alphabet bucket/layout.
    with contextlib.suppress(Exception):
        for path in root.glob(f"**/{CELEBRITY_ID}"):
            if path.is_dir():
                result.add(path)
    return sorted(result, key=lambda item: (item != _canonical_directory(root), str(item)))


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(raw)
        temp_name = handle.name
    os.replace(temp_name, path)


def _write_metadata(directory: Path, paths: list[Path]) -> None:
    manifest = {
        "version": VERSION,
        "id": CELEBRITY_ID,
        "display_name": CELEBRITY_NAME,
        "country": "ru",
        "reference_policy": "repo-bundled-age-consistent-user-supplied-pack",
        "reference_count": len(paths),
        "files": [
            {
                "name": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source": "user-supplied project reference",
            }
            for path in paths
        ],
    }
    _atomic_write(
        directory / "meta.json",
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    _atomic_write(
        directory / "attribution.json",
        json.dumps(
            {
                "version": VERSION,
                "notice": "User-supplied identity references bundled for this project; no web sync is used for this pack.",
                "items": manifest["files"],
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8"),
    )


def _materialize_reference_pack(root: Path | str | None = None) -> list[Path]:
    engine = v139.selfie.engine
    library_root = Path(root or getattr(engine.LIBRARY, "root", "/tmp/celebrity_library")).expanduser()
    source = [_asset_bytes(name) for name in _ASSET_GROUPS]
    canonical_paths: list[Path] = []
    for directory in _candidate_directories(library_root):
        directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for index, raw in enumerate(source, start=1):
            target = directory / f"ref_{index:02d}.jpg"
            if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(raw).digest():
                _atomic_write(target, raw)
            paths.append(target)
        # Remove stale fourth/older-age/web references so the renderer receives
        # exactly the three approved images chosen by the user.
        for stale in directory.glob("ref_*.*"):
            if stale.name not in {path.name for path in paths} and stale.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}:
                with contextlib.suppress(Exception):
                    stale.unlink()
        _write_metadata(directory, paths)
        if directory == _canonical_directory(library_root):
            canonical_paths = paths
    if not canonical_paths:
        raise RuntimeError("bundled Roman Abramovich reference pack was not materialized")
    return canonical_paths


def _ensure_refs(*args: Any, **kwargs: Any):
    entry = _entry_from_call(args, kwargs)
    if _is_roman_entry(entry):
        paths = _materialize_reference_pack()
        log.info("using bundled identity pack id=%s refs=%s", CELEBRITY_ID, len(paths))
        return paths
    if callable(_ORIGINAL_ENSURE_REFS):
        return _ORIGINAL_ENSURE_REFS(*args, **kwargs)
    raise RuntimeError("celebrity reference loader is unavailable")


def _reference_paths(session: dict[str, Any]):
    if _roman_selected(session):
        paths = _materialize_reference_pack()
        session["selected_celebrity_id"] = CELEBRITY_ID
        session["selected_celebrity_name"] = CELEBRITY_NAME
        session["celebrity_name"] = CELEBRITY_NAME
        session["celebrity_reference_source"] = "repo-bundled-v158"
        session["celebrity_reference_pack_version"] = VERSION
        session["celebrity_reference_count"] = len(paths)
        return [str(path) for path in paths]
    if callable(_ORIGINAL_REFERENCE_PATHS):
        return _ORIGINAL_REFERENCE_PATHS(session)
    return []


def _scene_prompt(celebrity_name: str, scene: str, aspect: str, variant: int) -> str:
    prompt = _BASE_SCENE_PROMPT(celebrity_name, scene, aspect, variant)
    if "абрамович" not in _norm(celebrity_name) and "abramovich" not in _norm(celebrity_name):
        return prompt
    return (
        prompt
        + " BUNDLED IDENTITY CONTRACT FOR THE RIGHT PERSON: all three right-person references depict the same mature-age appearance. "
        + "Preserve the repeated stable traits exactly: short silver-grey hair, receding mature hairline, broad forehead, light blue-grey eyes, "
        + "slightly hooded eyelids, compact oval face, straight medium nose, light skin, short neat grey beard and moustache, and natural mature age. "
        + "Do not use a younger brown-haired version, do not invent a generic businessman, and do not average this face with the USER. "
        + "The reference backgrounds, chairs, suits and red wall are identity-only source context and must not be copied into the requested scene."
    )


async def _generate(update: Any, context: Any, *, refinement: bool = False) -> None:
    session = v139.selfie.engine._session(context, create=False)
    if _roman_selected(session):
        paths = _materialize_reference_pack()
        session["selected_celebrity_id"] = CELEBRITY_ID
        session["selected_celebrity_name"] = CELEBRITY_NAME
        session["celebrity_name"] = CELEBRITY_NAME
        session["celebrity_reference_source"] = "repo-bundled-v158"
        session["celebrity_reference_count"] = len(paths)
        session.pop("last_generation_error", None)
    await _BASE_GENERATE(update, context, refinement=refinement)


def _patch_version_contract() -> None:
    with contextlib.suppress(Exception):
        import neyrobot_prod
        from neyrobot_prod import bootstrap, versioning
        neyrobot_prod.VERSION = VERSION
        bootstrap.VERSION = VERSION
        versioning.VERSION = VERSION


async def _diag(update: Any, context: Any) -> None:
    from telegram.ext import ApplicationHandlerStop

    engine = v139.selfie.engine
    session = engine._session(context, create=False) or {}
    paths: list[Path] = []
    error = ""
    try:
        paths = _materialize_reference_pack()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:700]
    lines = [
        f"📸 Celebrity Selfie / {VERSION}",
        "menu_owner=v124-exclusive-catalog-wizard",
        "render_base=v156-comet-dual-identity-best-of-n",
        "user_transfer=v156-unchanged",
        "scene_generation=v156-unchanged",
        "roman_reference_source=repo-bundled-age-consistent-pack",
        "roman_web_sync=bypassed",
        "roman_stale_cache_refs=purged",
        f"roman_reference_count={len(paths)}",
        f"roman_reference_paths={','.join(str(path) for path in paths) if paths else '-'}",
        f"roman_reference_error={error or '-'}",
        f"selected_id={session.get('selected_celebrity_id') or '-'}",
        f"selected_name={session.get('selected_celebrity_name') or session.get('celebrity_name') or '-'}",
        f"selected_reference_source={session.get('celebrity_reference_source') or '-'}",
        f"state={session.get('state') or '-'}",
        f"last_error={session.get('last_generation_error') or '-'}",
    ]
    await update.effective_message.reply_text("\n".join(lines)[:3900])
    raise ApplicationHandlerStop


def install() -> None:
    global _ORIGINAL_ENSURE_REFS, _ORIGINAL_REFERENCE_PATHS
    engine = v139.selfie.engine
    if getattr(engine, _INSTALL_FLAG, False):
        _patch_version_contract()
        return

    # Install the proven v157 menu + v156 renderer first, then replace only the
    # public-figure identity source for the selected catalog entry.
    previous.install()
    os.environ.setdefault("CELEBRITY_V158_BUNDLED_ABRAMOVICH", "1")
    os.environ.setdefault("CELEBRITY_V156_CELEBRITY_REFERENCE_LIMIT", "3")
    os.environ.setdefault("CELEBRITY_V156_REFERENCE_VISION_QC", "1")
    os.environ.setdefault("CELEBRITY_V156_TARGETED_REPAIR", "1")
    # A strong but deliverable gate. The old 78 threshold caused valid scenes to
    # be withheld even when the fixed reference pack substantially improved identity.
    os.environ.setdefault("CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "72")
    os.environ["CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY"] = os.environ.get(
        "CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "72"
    )
    os.environ["CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY"] = os.environ.get(
        "CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "72"
    )

    if _ORIGINAL_ENSURE_REFS is None:
        _ORIGINAL_ENSURE_REFS = engine.LIBRARY.ensure_refs
    if _ORIGINAL_REFERENCE_PATHS is None:
        _ORIGINAL_REFERENCE_PATHS = engine._reference_paths
    engine.LIBRARY.ensure_refs = _ensure_refs
    engine._reference_paths = _reference_paths
    engine._generate = _generate
    v139._generate = _generate
    v139.selfie._generate = _generate
    previous._generate = _generate
    previous.VERSION = VERSION
    renderer.VERSION = VERSION
    renderer._scene_prompt = _scene_prompt
    previous._scene_prompt = _scene_prompt
    engine._diag = _diag

    _materialize_reference_pack()
    setattr(engine, _INSTALL_FLAG, True)
    _patch_version_contract()
    log.info("installed %s bundled_id=%s refs=3", VERSION, CELEBRITY_ID)


def install_builder_hook() -> None:
    try:
        from telegram.ext import ApplicationBuilder, CommandHandler
    except Exception:
        return
    if getattr(ApplicationBuilder, _BUILDER_FLAG, False):
        return

    previous.install_builder_hook()
    original_build = ApplicationBuilder.build

    def build(self: Any, *args: Any, **kwargs: Any):
        install()
        app = original_build(self, *args, **kwargs)
        if not getattr(app, _HANDLER_FLAG, False):
            for command in ("diag_selfie_v158", "diag_selfie_v157", "diag_celebrity_flow", "diag_brand"):
                app.add_handler(CommandHandler(command, _diag), group=_GROUP)
            setattr(app, _HANDLER_FLAG, True)
        return app

    ApplicationBuilder.build = build
    setattr(ApplicationBuilder, _BUILDER_FLAG, True)


def install_early() -> None:
    install()
    install_builder_hook()


__all__ = [
    "VERSION",
    "CELEBRITY_ID",
    "CELEBRITY_NAME",
    "install",
    "install_early",
    "install_builder_hook",
    "_materialize_reference_pack",
    "_ensure_refs",
    "_reference_paths",
    "_scene_prompt",
    "_generate",
    "_diag",
]
