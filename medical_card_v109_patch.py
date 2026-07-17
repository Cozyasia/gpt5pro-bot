# -*- coding: utf-8 -*-
"""Neyro-Bot Medical Card v109.

Subscription-gated personal medical archive for PRO and ULTIMATE users.
The patch is loaded from secret_loader.py and applies after v108 medical analysis.
It intentionally keeps the existing medical analysis available to every tariff;
only persistent medical-card features are gated.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "v109-medical-card-pro-ultimate-2026-07-17"
PATCH_FLAG = "_MEDICAL_CARD_V109_PATCHED"
POLICY_VERSION = "medical-card-v1-2026-07-17"
MAX_PENDING_SECONDS = 24 * 3600

CATEGORY_LABELS = {
    "labs": "🧪 Лабораторные анализы",
    "imaging": "🖼 Исследования",
    "conclusion": "🧾 Заключения врачей",
    "prescription": "💊 Назначения",
    "other": "📎 Другие документы",
}


def _now() -> int:
    return int(time.time())


def _clean(value: Any, limit: int = 24000) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return text[:limit]


def _safe_filename(name: str, default: str = "medical_document") -> str:
    name = Path(name or default).name
    name = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._ -]+", "_", name).strip(" ._")
    return (name or default)[:120]


def _db_path(mod: Any) -> str:
    return os.path.abspath(str(getattr(mod, "DB_PATH", "subs.db")))


def _connect(mod: Any) -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(mod), timeout=30)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _storage_root(mod: Any) -> Path:
    configured = (os.environ.get("MEDICAL_CARD_STORAGE_DIR") or "").strip()
    if configured:
        root = Path(configured)
    else:
        db_parent = Path(_db_path(mod)).parent
        root = db_parent / "medical_card_files"
    root.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception):
        os.chmod(root, 0o700)
    return root


def _fernet(mod: Any):
    from cryptography.fernet import Fernet

    raw = (os.environ.get("MEDICAL_CARD_ENCRYPTION_KEY") or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("ascii"))
        except Exception:
            pass
    token = str(getattr(mod, "BOT_TOKEN", "") or os.environ.get("BOT_TOKEN") or "")
    material = hashlib.sha256(("neyro-medcard-v1|" + token).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _enc(mod: Any, value: Any) -> bytes:
    data = value if isinstance(value, (bytes, bytearray)) else _clean(value).encode("utf-8")
    return _fernet(mod).encrypt(bytes(data))


def _dec(mod: Any, value: Any, *, binary: bool = False):
    if value is None:
        return b"" if binary else ""
    try:
        data = _fernet(mod).decrypt(bytes(value))
    except Exception:
        return b"" if binary else ""
    return data if binary else data.decode("utf-8", errors="replace")


def _init_db(mod: Any) -> None:
    con = _connect(mod)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS medical_consents (
            user_id INTEGER PRIMARY KEY,
            accepted_ts INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            revoked_ts INTEGER DEFAULT 0,
            auto_save INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS medical_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            relation TEXT DEFAULT 'self',
            is_default INTEGER DEFAULT 0,
            created_ts INTEGER NOT NULL,
            UNIQUE(owner_user_id, display_name)
        );
        CREATE INDEX IF NOT EXISTS idx_med_profiles_owner ON medical_profiles(owner_user_id, is_default DESC, id);
        CREATE TABLE IF NOT EXISTS medical_documents (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            specialty TEXT DEFAULT '',
            title TEXT NOT NULL,
            document_date TEXT DEFAULT '',
            source_type TEXT DEFAULT '',
            original_filename TEXT DEFAULT '',
            mime_type TEXT DEFAULT 'application/octet-stream',
            encrypted_path TEXT DEFAULT '',
            source_text_enc BLOB,
            analysis_enc BLOB,
            metadata_enc BLOB,
            created_ts INTEGER NOT NULL,
            updated_ts INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            FOREIGN KEY(profile_id) REFERENCES medical_profiles(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_med_docs_owner_profile_date ON medical_documents(owner_user_id, profile_id, created_ts DESC);
        CREATE INDEX IF NOT EXISTS idx_med_docs_category ON medical_documents(owner_user_id, profile_id, category, created_ts DESC);
        CREATE TABLE IF NOT EXISTS medical_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            profile_id INTEGER NOT NULL,
            label_enc BLOB NOT NULL,
            detail_enc BLOB,
            priority TEXT DEFAULT 'routine',
            created_ts INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES medical_documents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS medical_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            profile_id INTEGER NOT NULL,
            name_enc BLOB NOT NULL,
            value_text_enc BLOB,
            numeric_value REAL,
            unit_enc BLOB,
            reference_enc BLOB,
            measured_date TEXT DEFAULT '',
            created_ts INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES medical_documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_med_measurements_profile_date ON medical_measurements(profile_id, measured_date, created_ts);
        CREATE TABLE IF NOT EXISTS medical_medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id TEXT NOT NULL,
            profile_id INTEGER NOT NULL,
            name_enc BLOB NOT NULL,
            dosage_enc BLOB,
            schedule_enc BLOB,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            source_kind TEXT DEFAULT 'document',
            status TEXT DEFAULT 'recorded',
            created_ts INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES medical_documents(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS medical_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            profile_id INTEGER NOT NULL,
            document_id TEXT,
            due_ts INTEGER DEFAULT 0,
            title_enc BLOB NOT NULL,
            note_enc BLOB,
            status TEXT DEFAULT 'planned',
            created_ts INTEGER NOT NULL,
            FOREIGN KEY(document_id) REFERENCES medical_documents(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS medical_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            object_type TEXT DEFAULT '',
            object_id TEXT DEFAULT '',
            created_ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_med_audit_owner ON medical_audit_log(owner_user_id, created_ts DESC);
        """
    )
    con.commit(); con.close(); _storage_root(mod)


def _audit(mod: Any, user_id: int, action: str, object_type: str = "", object_id: str = "") -> None:
    with contextlib.suppress(Exception):
        con = _connect(mod)
        con.execute("INSERT INTO medical_audit_log(owner_user_id, action, object_type, object_id, created_ts) VALUES (?,?,?,?,?)", (int(user_id), action[:80], object_type[:40], object_id[:80], _now()))
        con.commit(); con.close()


def _is_unlimited(mod: Any, user_id: int, username: str = "") -> bool:
    fn = getattr(mod, "is_unlimited", None)
    if callable(fn):
        with contextlib.suppress(Exception):
            return bool(fn(int(user_id), username or ""))
    return int(user_id) == int(getattr(mod, "OWNER_ID", 0) or 0)


def _tier(mod: Any, user_id: int) -> str:
    fn = getattr(mod, "get_subscription_tier", None)
    if callable(fn):
        with contextlib.suppress(Exception):
            return str(fn(int(user_id)) or "free").lower()
    return "free"


def _eligible(mod: Any, user: Any) -> bool:
    uid = int(getattr(user, "id", 0) or 0)
    username = str(getattr(user, "username", "") or "")
    return _tier(mod, uid) in {"pro", "ultimate"} or _is_unlimited(mod, uid, username)


def _consent_row(mod: Any, user_id: int):
    _init_db(mod)
    con = _connect(mod)
    row = con.execute("SELECT accepted_ts, policy_version, revoked_ts, auto_save FROM medical_consents WHERE user_id=?", (int(user_id),)).fetchone()
    con.close(); return row


def _has_consent(mod: Any, user_id: int) -> bool:
    row = _consent_row(mod, user_id)
    return bool(row and int(row[0] or 0) > 0 and int(row[2] or 0) == 0)


def _auto_save(mod: Any, user_id: int) -> bool:
    row = _consent_row(mod, user_id)
    return bool(row and int(row[3] or 0) == 1 and int(row[2] or 0) == 0)


def _accept_consent(mod: Any, user_id: int) -> int:
    _init_db(mod); now = _now(); con = _connect(mod)
    con.execute("INSERT INTO medical_consents(user_id, accepted_ts, policy_version, revoked_ts, auto_save) VALUES (?,?,?,?,0) ON CONFLICT(user_id) DO UPDATE SET accepted_ts=excluded.accepted_ts, policy_version=excluded.policy_version, revoked_ts=0", (int(user_id), now, POLICY_VERSION, 0))
    con.execute("INSERT OR IGNORE INTO medical_profiles(owner_user_id, display_name, relation, is_default, created_ts) VALUES (?,?,?,?,?)", (int(user_id), "Моя карта", "self", 1, now))
    con.commit(); row = con.execute("SELECT id FROM medical_profiles WHERE owner_user_id=? ORDER BY is_default DESC, id LIMIT 1", (int(user_id),)).fetchone(); con.close()
    _audit(mod, user_id, "consent_accept", "consent", POLICY_VERSION)
    return int(row[0]) if row else 0


def _profiles(mod: Any, user_id: int) -> list[dict]:
    _init_db(mod); con = _connect(mod)
    rows = con.execute("SELECT id, display_name, relation, is_default, created_ts FROM medical_profiles WHERE owner_user_id=? ORDER BY is_default DESC, id", (int(user_id),)).fetchall(); con.close()
    return [{"id": int(r[0]), "name": r[1], "relation": r[2] or "other", "default": bool(r[3]), "created_ts": int(r[4])} for r in rows]


def _default_profile_id(mod: Any, user_id: int) -> int:
    rows = _profiles(mod, user_id)
    if rows: return int(rows[0]["id"])
    if _has_consent(mod, user_id): return _accept_consent(mod, user_id)
    return 0


def _profile_owned(mod: Any, user_id: int, profile_id: int) -> bool:
    con = _connect(mod); row = con.execute("SELECT 1 FROM medical_profiles WHERE id=? AND owner_user_id=?", (int(profile_id), int(user_id))).fetchone(); con.close(); return bool(row)


def _set_default_profile(mod: Any, user_id: int, profile_id: int) -> None:
    if not _profile_owned(mod, user_id, profile_id): return
    con = _connect(mod); con.execute("UPDATE medical_profiles SET is_default=0 WHERE owner_user_id=?", (int(user_id),)); con.execute("UPDATE medical_profiles SET is_default=1 WHERE id=? AND owner_user_id=?", (int(profile_id), int(user_id))); con.commit(); con.close(); _audit(mod, user_id, "profile_default", "profile", str(profile_id))


def _profile_name(mod: Any, user_id: int, profile_id: int) -> str:
    con = _connect(mod); row = con.execute("SELECT display_name FROM medical_profiles WHERE id=? AND owner_user_id=?", (int(profile_id), int(user_id))).fetchone(); con.close(); return str(row[0]) if row else "Моя карта"


def _add_profile(mod: Any, user_id: int, display_name: str, relation: str = "relative") -> tuple[bool, str]:
    name = re.sub(r"\s+", " ", _clean(display_name, 60)).strip()
    if len(name) < 2: return False, "Название профиля слишком короткое."
    try:
        con = _connect(mod); count = int(con.execute("SELECT COUNT(*) FROM medical_profiles WHERE owner_user_id=?", (int(user_id),)).fetchone()[0])
        if count >= 8: con.close(); return False, "Можно создать не более 8 профилей."
        con.execute("INSERT INTO medical_profiles(owner_user_id, display_name, relation, is_default, created_ts) VALUES (?,?,?,?,?)", (int(user_id), name, relation, 0, _now())); con.commit(); con.close(); _audit(mod, user_id, "profile_create", "profile", name); return True, name
    except sqlite3.IntegrityError:
        return False, "Профиль с таким названием уже существует."


def _write_encrypted_file(mod: Any, user_id: int, document_id: str, data: bytes) -> str:
    if not data: return ""
    max_mb = max(1, int(os.environ.get("MEDICAL_CARD_MAX_FILE_MB", "20") or 20))
    if len(data) > max_mb * 1024 * 1024: raise ValueError(f"Файл больше допустимого лимита {max_mb} МБ")
    user_dir = _storage_root(mod) / hashlib.sha256(str(user_id).encode()).hexdigest()[:20]
    user_dir.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(Exception): os.chmod(user_dir, 0o700)
    path = user_dir / f"{document_id}.bin"; path.write_bytes(_enc(mod, data))
    with contextlib.suppress(Exception): os.chmod(path, 0o600)
    return str(path)


def _read_encrypted_file(mod: Any, path: str) -> bytes:
    if not path: return b""
    p = Path(path)
    if not p.exists() or not p.is_file(): return b""
    return _dec(mod, p.read_bytes(), binary=True)


def _extract_json(text: str) -> dict:
    raw = _clean(text, 30000); raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    try:
        data = json.loads(raw); return data if isinstance(data, dict) else {}
    except Exception: pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        with contextlib.suppress(Exception):
            data = json.loads(raw[start:end+1]); return data if isinstance(data, dict) else {}
    return {}


def _fallback_metadata(source_text: str, analysis: str, track: str, filename: str) -> dict:
    all_text = f"{source_text}\n{analysis}\n{filename}".lower()
    if re.search(r"анализ|гемоглоб|ттг|т4|феррит|глюкоз|холест|лейкоц|эритроц", all_text): category = "labs"
    elif re.search(r"узи|мрт|кт|рентген|томограф|tirads|рентгенограф", all_text): category = "imaging"
    elif re.search(r"назначен|принимать|дозиров|рецепт|препарат|таблет", all_text): category = "prescription"
    elif re.search(r"заключение|эпикриз|консультац|врач", all_text): category = "conclusion"
    else: category = "other"
    specialty = ""
    for label, pattern in (("Эндокринология", r"щитовид|ттг|тиреоид|tirads"), ("Гинекология", r"матк|яичник|эндометр|аденомиоз|кист"), ("Кардиология", r"сердц|экг|давлен|кардио"), ("Неврология", r"головн|позвоноч|невролог|мрт"), ("Гастроэнтерология", r"печен|желч|желуд|кишеч")):
        if re.search(pattern, all_text): specialty = label; break
    title = _safe_filename(filename, CATEGORY_LABELS.get(category, "Медицинский документ")).rsplit(".", 1)[0]
    if title.lower() in {"medical_document", "photo", "document", "file"}: title = CATEGORY_LABELS.get(category, "Медицинский документ").split(" ", 1)[-1]
    return {"title": title[:90], "document_date": "", "category": category, "specialty": specialty, "summary": _clean(analysis, 700), "key_findings": [], "measurements": [], "medications": [], "follow_up": [], "organ_systems": []}


async def _classify(mod: Any, pending: dict) -> dict:
    source_text = _clean(pending.get("source_text"), 16000); analysis = _clean(pending.get("analysis"), 12000); filename = _safe_filename(pending.get("filename") or "medical_document"); track = _clean(pending.get("track"), 80)
    prompt = f'''Ты структурируешь медицинский документ для личной медицинской карты. Верни только один JSON-объект без Markdown. Не ставь новый диагноз и не придумывай отсутствующие данные.
Поля: title, document_date (YYYY-MM-DD или пусто), category (labs|imaging|conclusion|prescription|other), specialty, organ_systems, summary, key_findings (label/detail/priority routine|attention|urgent), measurements (name/value_text/numeric_value/unit/reference), medications (name/dosage/schedule/start_date/end_date/source_kind), follow_up (title/suggested_period/reason).
Сохраняй точные размеры, единицы и категории риска. Медикаменты добавляй только если они прямо назначены в источнике. Рекомендации ИИ не записывай как официальное назначение врача.
Имя файла: {filename}\nТрек: {track}\nИзвлечённый текст:\n{source_text}\nСправочный разбор:\n{analysis}'''
    data = {}
    try: data = _extract_json(await mod.ask_openai_text(prompt))
    except Exception: pass
    fallback = _fallback_metadata(source_text, analysis, track, filename)
    if not data: return fallback
    result = dict(fallback)
    for key in result:
        if key in data and data[key] not in (None, "", []): result[key] = data[key]
    if result.get("category") not in CATEGORY_LABELS: result["category"] = fallback["category"]
    result["title"] = _clean(result.get("title") or fallback["title"], 100); result["specialty"] = _clean(result.get("specialty"), 80); result["document_date"] = _clean(result.get("document_date"), 20)
    return result


def _insert_structured_rows(mod: Any, con: sqlite3.Connection, document_id: str, profile_id: int, meta: dict) -> None:
    created = _now()
    for item in (meta.get("key_findings") or [])[:30]:
        if not isinstance(item, dict) or not _clean(item.get("label"), 300): continue
        con.execute("INSERT INTO medical_findings(document_id, profile_id, label_enc, detail_enc, priority, created_ts) VALUES (?,?,?,?,?,?)", (document_id, profile_id, _enc(mod, _clean(item.get("label"), 500)), _enc(mod, _clean(item.get("detail"), 1500)), _clean(item.get("priority") or "routine", 20), created))
    for item in (meta.get("measurements") or [])[:100]:
        if not isinstance(item, dict) or not _clean(item.get("name"), 200): continue
        num = item.get("numeric_value")
        try: num = float(num) if num not in (None, "") else None
        except Exception: num = None
        con.execute("INSERT INTO medical_measurements(document_id, profile_id, name_enc, value_text_enc, numeric_value, unit_enc, reference_enc, measured_date, created_ts) VALUES (?,?,?,?,?,?,?,?,?)", (document_id, profile_id, _enc(mod, _clean(item.get("name"), 300)), _enc(mod, _clean(item.get("value_text"), 300)), num, _enc(mod, _clean(item.get("unit"), 100)), _enc(mod, _clean(item.get("reference"), 300)), _clean(meta.get("document_date"), 20), created))
    for item in (meta.get("medications") or [])[:50]:
        if not isinstance(item, dict) or not _clean(item.get("name"), 200): continue
        con.execute("INSERT INTO medical_medications(document_id, profile_id, name_enc, dosage_enc, schedule_enc, start_date, end_date, source_kind, status, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?)", (document_id, profile_id, _enc(mod, _clean(item.get("name"), 300)), _enc(mod, _clean(item.get("dosage"), 300)), _enc(mod, _clean(item.get("schedule"), 500)), _clean(item.get("start_date"), 20), _clean(item.get("end_date"), 20), _clean(item.get("source_kind") or "document", 30), "recorded", created))
    for item in (meta.get("follow_up") or [])[:20]:
        if not isinstance(item, dict) or not _clean(item.get("title"), 300): continue
        note = " — ".join(x for x in [_clean(item.get("suggested_period"), 150), _clean(item.get("reason"), 500)] if x)
        con.execute("INSERT INTO medical_reminders(owner_user_id, profile_id, document_id, due_ts, title_enc, note_enc, status, created_ts) VALUES (?,?,?,?,?,?,?,?)", (0, profile_id, document_id, 0, _enc(mod, _clean(item.get("title"), 400)), _enc(mod, note), "suggested", created))


async def _save_pending(mod: Any, update: Any, context: Any, profile_id: int | None = None) -> tuple[bool, str, str]:
    user = update.effective_user; uid = int(user.id); pending = context.user_data.get("medcard_pending") or {}
    if not pending: return False, "Нет нового медицинского разбора для сохранения.", ""
    if _now() - int(pending.get("created_ts") or 0) > MAX_PENDING_SECONDS: context.user_data.pop("medcard_pending", None); return False, "Срок сохранения этого временного разбора истёк. Загрузите документ снова.", ""
    if not _eligible(mod, user): return False, "Медицинская карта доступна только в PRO и ULTIMATE.", ""
    if not _has_consent(mod, uid): return False, "Сначала создайте медицинскую карту и подтвердите согласие на хранение.", ""
    profile_id = int(profile_id or _default_profile_id(mod, uid))
    if not _profile_owned(mod, uid, profile_id): return False, "Профиль не найден.", ""
    meta = await _classify(mod, pending); document_id = str(uuid.uuid4()); file_path = ""
    try:
        file_path = _write_encrypted_file(mod, uid, document_id, bytes(pending.get("file_bytes") or b"")); now = _now(); con = _connect(mod); con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO medical_documents(id, owner_user_id, profile_id, category, specialty, title, document_date, source_type, original_filename, mime_type, encrypted_path, source_text_enc, analysis_enc, metadata_enc, created_ts, updated_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (document_id, uid, profile_id, meta.get("category") or "other", _clean(meta.get("specialty"), 80), _clean(meta.get("title"), 100), _clean(meta.get("document_date"), 20), _clean(pending.get("source_type"), 40), _safe_filename(pending.get("filename") or "medical_document"), _clean(pending.get("mime_type") or "application/octet-stream", 100), file_path, _enc(mod, pending.get("source_text") or ""), _enc(mod, pending.get("analysis") or ""), _enc(mod, json.dumps(meta, ensure_ascii=False)), now, now, "active"))
        _insert_structured_rows(mod, con, document_id, profile_id, meta); con.execute("UPDATE medical_reminders SET owner_user_id=? WHERE document_id=?", (uid, document_id)); con.commit(); con.close()
    except Exception as exc:
        if file_path:
            with contextlib.suppress(Exception): Path(file_path).unlink()
        return False, f"Не удалось сохранить документ: {type(exc).__name__}", ""
    context.user_data.pop("medcard_pending", None); _audit(mod, uid, "document_save", "document", document_id)
    label = CATEGORY_LABELS.get(meta.get("category"), CATEGORY_LABELS["other"]); profile_name = _profile_name(mod, uid, profile_id)
    return True, f"✅ Сохранено в «{profile_name}» → {label}.\nДокумент: {meta.get('title')}", document_id


def _doc_row(mod: Any, user_id: int, doc_id: str):
    con = _connect(mod); row = con.execute("SELECT id, profile_id, category, specialty, title, document_date, source_type, original_filename, mime_type, encrypted_path, source_text_enc, analysis_enc, metadata_enc, created_ts FROM medical_documents WHERE id=? AND owner_user_id=? AND status='active'", (doc_id, int(user_id))).fetchone(); con.close(); return row


def _list_docs(mod: Any, user_id: int, profile_id: int, category: str = "", limit: int = 12) -> list[dict]:
    con = _connect(mod); sql = "SELECT id, category, specialty, title, document_date, original_filename, created_ts FROM medical_documents WHERE owner_user_id=? AND profile_id=? AND status='active'"; params: list[Any] = [int(user_id), int(profile_id)]
    if category: sql += " AND category=?"; params.append(category)
    sql += " ORDER BY COALESCE(NULLIF(document_date,''), datetime(created_ts,'unixepoch')) DESC, created_ts DESC LIMIT ?"; params.append(int(limit))
    rows = con.execute(sql, params).fetchall(); con.close()
    return [{"id": r[0], "category": r[1], "specialty": r[2] or "", "title": r[3], "date": r[4] or "", "filename": r[5] or "", "created_ts": int(r[6])} for r in rows]


def _fmt_date(value: str, ts: int = 0) -> str:
    if value:
        with contextlib.suppress(Exception): return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    if ts: return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")
    return "дата не указана"


def _chunk(text: str, limit: int = 3800) -> list[str]:
    text = _clean(text, 50000)
    if not text: return ["Нет данных."]
    out = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 3: cut = text.rfind("\n", 0, limit)
        if cut < limit // 4: cut = limit
        out.append(text[:cut].strip()); text = text[cut:].lstrip()
    if text: out.append(text)
    return out


def _kb(mod: Any, rows: list[list[tuple[str, str]]]):
    return mod.InlineKeyboardMarkup([[mod.InlineKeyboardButton(text, callback_data=data) for text, data in row] for row in rows])


def _upgrade_kb(mod: Any):
    return _kb(mod, [[("🚀 PRO", "plan:pro"), ("👑 ULTIMATE", "plan:ultimate")], [("⬅️ Назад в медицину", "medcard:back_med")]])


def _consent_kb(mod: Any):
    return _kb(mod, [[("✅ Создать карту и согласиться", "medcard:consent_accept")], [("🚫 Не создавать", "medcard:back_med")]])


def _card_main_kb(mod: Any):
    return _kb(mod, [[("🧭 Сводка", "medcard:summary"), ("🕒 Хронология", "medcard:timeline")], [("🧪 Анализы", "medcard:list:labs"), ("🖼 Исследования", "medcard:list:imaging")], [("🧾 Заключения", "medcard:list:conclusion"), ("💊 Назначения", "medcard:meds")], [("📈 Динамика показателей", "medcard:measurements")], [("📎 Все документы", "medcard:list:all"), ("🔎 Поиск", "medcard:search")], [("📤 Экспорт PDF", "medcard:export"), ("👥 Профили", "medcard:profiles")], [("⚙️ Настройки", "medcard:settings")], [("⬅️ Назад в медицину", "medcard:back_med")]])


def _pending_save_kb(mod: Any, uid: int):
    rows = []; profiles = _profiles(mod, uid) if _has_consent(mod, uid) else []
    if profiles:
        rows.append([("✅ Сохранить в карту", "medcard:save_default")])
        if len(profiles) > 1: rows.append([("👤 Выбрать профиль", "medcard:save_choose")])
    else: rows.append([("📁 Создать карту и сохранить", "medcard:create_for_pending")])
    rows.append([("🚫 Не сохранять", "medcard:discard_pending")]); return _kb(mod, rows)


def _profile_select_kb(mod: Any, user_id: int, prefix: str = "save"):
    rows = []
    for p in _profiles(mod, user_id):
        mark = "⭐ " if p["default"] else ""; rows.append([(f"{mark}{p['name']}", f"medcard:{prefix}_profile:{p['id']}")])
    rows.append([("➕ Добавить профиль", "medcard:profile_add")]); rows.append([("⬅️ Назад", "medcard:open")]); return _kb(mod, rows)


def _doc_kb(mod: Any, doc_id: str, has_file: bool):
    rows = [[("🩺 Разбор бота", f"medcard:analysis:{doc_id}")]]
    if has_file: rows.append([("📄 Открыть оригинал", f"medcard:original:{doc_id}")])
    rows.extend([[("🗑 Удалить", f"medcard:delete_ask:{doc_id}")], [("⬅️ К карте", "medcard:open")]]); return _kb(mod, rows)


def _card_stats(mod: Any, user_id: int, profile_id: int) -> dict:
    con = _connect(mod); total = int(con.execute("SELECT COUNT(*) FROM medical_documents WHERE owner_user_id=? AND profile_id=? AND status='active'", (user_id, profile_id)).fetchone()[0]); categories = dict(con.execute("SELECT category, COUNT(*) FROM medical_documents WHERE owner_user_id=? AND profile_id=? AND status='active' GROUP BY category", (user_id, profile_id)).fetchall()); meds = int(con.execute("SELECT COUNT(*) FROM medical_medications WHERE profile_id=?", (profile_id,)).fetchone()[0]); reminders = int(con.execute("SELECT COUNT(*) FROM medical_reminders WHERE owner_user_id=? AND profile_id=? AND status IN ('suggested','planned')", (user_id, profile_id)).fetchone()[0]); con.close(); return {"total": total, "categories": categories, "meds": meds, "reminders": reminders}


async def _show_card(mod: Any, update: Any, context: Any, edit: bool = False) -> None:
    user = update.effective_user; uid = int(user.id); msg = update.callback_query.message if update.callback_query else update.effective_message
    if not _eligible(mod, user):
        text = "🔒 Моя медицинская карта доступна только по подписке PRO или ULTIMATE.\n\nОстальные функции медицинского режима продолжают работать на вашем тарифе без постоянного хранения документов.\n\nВ PRO/ULTIMATE карта хранит оригиналы, разборы, хронологию, показатели и назначения."
        if edit and update.callback_query: await msg.edit_text(text, reply_markup=_upgrade_kb(mod))
        else: await msg.reply_text(text, reply_markup=_upgrade_kb(mod))
        return
    if not _has_consent(mod, uid):
        text = "📁 Моя медицинская карта\n\nКарта создаётся только после вашего явного согласия. В ней могут храниться чувствительные медицинские данные: загруженные документы, извлечённые показатели, справочные разборы и назначения из официальных документов.\n\nЗащита:\n• доступ только из вашего Telegram-аккаунта;\n• оригиналы и медицинский текст сохраняются в зашифрованном виде;\n• файлы не публикуются по открытым ссылкам;\n• любой документ или всю карту можно удалить;\n• карта не заменяет официальную медицинскую информационную систему.\n\nНажимая кнопку ниже, вы соглашаетесь на хранение этих данных для работы персональной медицинской карты."
        if edit and update.callback_query: await msg.edit_text(text, reply_markup=_consent_kb(mod))
        else: await msg.reply_text(text, reply_markup=_consent_kb(mod))
        return
    profile_id = _default_profile_id(mod, uid); profile_name = _profile_name(mod, uid, profile_id); stats = _card_stats(mod, uid, profile_id)
    text = f"📁 Моя медицинская карта\nПрофиль: {profile_name}\n\nДокументов: {stats['total']}\nИсследований: {stats['categories'].get('imaging', 0)}\nАнализов: {stats['categories'].get('labs', 0)}\nЗаключений: {stats['categories'].get('conclusion', 0)}\nЗаписей о лекарствах: {stats['meds']}\nРекомендовано проконтролировать: {stats['reminders']}\n\nВыберите раздел. Оригинал документа и справочный разбор хранятся отдельно."
    if edit and update.callback_query: await msg.edit_text(text, reply_markup=_card_main_kb(mod))
    else: await msg.reply_text(text, reply_markup=_card_main_kb(mod))


async def _show_docs(mod: Any, update: Any, category: str = "") -> None:
    uid = int(update.effective_user.id); profile_id = _default_profile_id(mod, uid); docs = _list_docs(mod, uid, profile_id, "" if category == "all" else category, 15); title = "📎 Все документы" if category in {"", "all"} else CATEGORY_LABELS.get(category, "Документы")
    if not docs: await update.callback_query.message.edit_text(f"{title}\n\nПока нет сохранённых документов.", reply_markup=_kb(mod, [[("⬅️ К карте", "medcard:open")]])); return
    lines = [title, f"Профиль: {_profile_name(mod, uid, profile_id)}", ""]; rows = []
    for idx, d in enumerate(docs, 1): lines.append(f"{idx}. {_fmt_date(d['date'], d['created_ts'])} — {d['title']}"); rows.append([(f"{idx}. {d['title'][:34]}", f"medcard:doc:{d['id']}")])
    rows.append([("⬅️ К карте", "medcard:open")]); await update.callback_query.message.edit_text("\n".join(lines), reply_markup=_kb(mod, rows))


async def _show_doc(mod: Any, update: Any, doc_id: str) -> None:
    uid = int(update.effective_user.id); row = _doc_row(mod, uid, doc_id)
    if not row: await update.callback_query.answer("Документ не найден", show_alert=True); return
    meta = {}
    with contextlib.suppress(Exception): meta = json.loads(_dec(mod, row[12]) or "{}")
    summary = _clean(meta.get("summary"), 900) or "Сводка не сформирована."; label = CATEGORY_LABELS.get(row[2], CATEGORY_LABELS["other"])
    text = f"{label}\n\n{row[4]}\nДата: {_fmt_date(row[5], row[13])}\nПрофиль: {_profile_name(mod, uid, row[1])}\n" + (f"Специальность: {row[3]}\n" if row[3] else "") + f"\nКратко:\n{summary}"
    await update.callback_query.message.edit_text(text[:3900], reply_markup=_doc_kb(mod, doc_id, bool(row[9])))


async def _show_summary(mod: Any, update: Any) -> None:
    uid = int(update.effective_user.id); profile_id = _default_profile_id(mod, uid); docs = _list_docs(mod, uid, profile_id, "", 8); con = _connect(mod)
    findings_rows = con.execute("SELECT label_enc, detail_enc, priority FROM medical_findings WHERE profile_id=? ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'attention' THEN 1 ELSE 2 END, id DESC LIMIT 10", (profile_id,)).fetchall(); rem_rows = con.execute("SELECT title_enc, note_enc, status FROM medical_reminders WHERE owner_user_id=? AND profile_id=? AND status IN ('suggested','planned') ORDER BY id DESC LIMIT 8", (uid, profile_id)).fetchall(); con.close()
    lines = ["🧭 Сводка здоровья", f"Профиль: {_profile_name(mod, uid, profile_id)}", ""]
    if findings_rows:
        lines.append("Требует внимания:")
        for label_enc, detail_enc, priority in findings_rows:
            prefix = "🔴" if priority == "urgent" else "🟠" if priority == "attention" else "•"; detail = _dec(mod, detail_enc); lines.append(f"{prefix} {_dec(mod, label_enc)}" + (f" — {detail}" if detail else ""))
    else: lines.append("Структурированных находок пока нет.")
    if rem_rows:
        lines.extend(["", "Контроль и рекомендации из документов:"])
        for title_enc, note_enc, _ in rem_rows:
            note = _dec(mod, note_enc); lines.append(f"• {_dec(mod, title_enc)}" + (f" — {note}" if note else ""))
    if docs:
        lines.extend(["", "Последние документы:"])
        for d in docs[:5]: lines.append(f"• {_fmt_date(d['date'], d['created_ts'])} — {d['title']}")
    await update.callback_query.message.edit_text("\n".join(lines)[:3900], reply_markup=_kb(mod, [[("⬅️ К карте", "medcard:open")]]))


async def _show_timeline(mod: Any, update: Any) -> None:
    uid = int(update.effective_user.id); pid = _default_profile_id(mod, uid); docs = _list_docs(mod, uid, pid, "", 30); lines = ["🕒 Медицинская хронология", f"Профиль: {_profile_name(mod, uid, pid)}", ""]
    if not docs: lines.append("Пока нет сохранённых событий.")
    else:
        for d in docs: lines.append(f"{_fmt_date(d['date'], d['created_ts'])}\n• {d['title']} — {CATEGORY_LABELS.get(d['category'], 'Документ')}")
    await update.callback_query.message.edit_text("\n\n".join(lines)[:3900], reply_markup=_kb(mod, [[("⬅️ К карте", "medcard:open")]]))


async def _show_measurements(mod: Any, update: Any) -> None:
    uid = int(update.effective_user.id); pid = _default_profile_id(mod, uid); con = _connect(mod); rows = con.execute("SELECT name_enc, value_text_enc, numeric_value, unit_enc, reference_enc, measured_date, created_ts FROM medical_measurements WHERE profile_id=? ORDER BY COALESCE(NULLIF(measured_date,''), datetime(created_ts,'unixepoch')) DESC, id DESC LIMIT 40", (pid,)).fetchall(); con.close(); lines = ["🧪 Распознанные показатели", f"Профиль: {_profile_name(mod, uid, pid)}", ""]
    if not rows: lines.append("Показатели пока не распознаны. Сохраните лабораторный анализ в карту.")
    else:
        for row in rows:
            name, value, unit, ref = _dec(mod, row[0]), _dec(mod, row[1]), _dec(mod, row[3]), _dec(mod, row[4]); line = f"• {_fmt_date(row[5], row[6])}: {name} — {value or row[2] or '—'} {unit}".rstrip(); line += f" (референс: {ref})" if ref else ""; lines.append(line)
    await update.callback_query.message.edit_text("\n".join(lines)[:3900], reply_markup=_kb(mod, [[("⬅️ К карте", "medcard:open")]]))


async def _show_meds(mod: Any, update: Any) -> None:
    uid = int(update.effective_user.id); pid = _default_profile_id(mod, uid); con = _connect(mod); rows = con.execute("SELECT name_enc, dosage_enc, schedule_enc, start_date, end_date, source_kind, status FROM medical_medications WHERE profile_id=? ORDER BY id DESC LIMIT 30", (pid,)).fetchall(); con.close(); lines = ["💊 Назначения и лекарства", f"Профиль: {_profile_name(mod, uid, pid)}", ""]
    if not rows: lines.append("Официальные назначения из документов пока не сохранены.")
    else:
        for row in rows:
            text = f"• {_dec(mod, row[0])}"; dosage, schedule = _dec(mod, row[1]), _dec(mod, row[2]); text += f" — {dosage}" if dosage else ""; text += f", {schedule}" if schedule else ""; text += f" ({row[3] or '?'} — {row[4] or '?'})" if row[3] or row[4] else ""; lines.append(text)
    lines.extend(["", "Важно: здесь отображается только то, что распознано как назначение из документа. Справочный ответ бота не считается назначением врача."])
    await update.callback_query.message.edit_text("\n".join(lines)[:3900], reply_markup=_kb(mod, [[("⬅️ К карте", "medcard:open")]]))


async def _show_profiles(mod: Any, update: Any) -> None:
    uid = int(update.effective_user.id); profiles = _profiles(mod, uid); lines = ["👥 Профили медицинской карты", ""]; rows = []
    for p in profiles: mark = "⭐" if p["default"] else "•"; lines.append(f"{mark} {p['name']}"); rows.append([(f"Сделать основным: {p['name'][:24]}", f"medcard:profile_default:{p['id']}")])
    rows.append([("➕ Добавить профиль", "medcard:profile_add")]); rows.append([("⬅️ К карте", "medcard:open")]); await update.callback_query.message.edit_text("\n".join(lines), reply_markup=_kb(mod, rows))


async def _show_settings(mod: Any, update: Any) -> None:
    uid = int(update.effective_user.id); auto = _auto_save(mod, uid); db_parent = str(Path(_db_path(mod)).parent); persistent_hint = "постоянный диск" if db_parent.startswith("/data") else "проверьте постоянный диск Render"
    text = f"⚙️ Настройки медицинской карты\n\nАвтосохранение после медицинского разбора: {'включено' if auto else 'выключено'}\nХранилище: {persistent_hint}\nОригиналы и медицинский текст: зашифрованы.\n\nПри выключенном автосохранении бот каждый раз спрашивает подтверждение. Удаление всей карты необратимо."
    kb = _kb(mod, [[("🔁 " + ("Выключить" if auto else "Включить") + " автосохранение", "medcard:auto_toggle")], [("🗑 Удалить всю карту", "medcard:delete_all_ask")], [("⬅️ К карте", "medcard:open")]])
    await update.callback_query.message.edit_text(text, reply_markup=kb)


def _delete_document(mod: Any, user_id: int, doc_id: str) -> bool:
    row = _doc_row(mod, user_id, doc_id)
    if not row: return False
    path = row[9]; con = _connect(mod); con.execute("DELETE FROM medical_documents WHERE id=? AND owner_user_id=?", (doc_id, int(user_id))); con.commit(); con.close()
    if path:
        with contextlib.suppress(Exception): Path(path).unlink()
    _audit(mod, user_id, "document_delete", "document", doc_id); return True


def _delete_all(mod: Any, user_id: int) -> None:
    con = _connect(mod); paths = [r[0] for r in con.execute("SELECT encrypted_path FROM medical_documents WHERE owner_user_id=?", (int(user_id),)).fetchall() if r[0]]; profile_ids = [r[0] for r in con.execute("SELECT id FROM medical_profiles WHERE owner_user_id=?", (int(user_id),)).fetchall()]; con.execute("BEGIN IMMEDIATE"); con.execute("DELETE FROM medical_reminders WHERE owner_user_id=?", (int(user_id),))
    for pid in profile_ids: con.execute("DELETE FROM medical_profiles WHERE id=?", (int(pid),))
    con.execute("UPDATE medical_consents SET revoked_ts=?, auto_save=0 WHERE user_id=?", (_now(), int(user_id))); con.execute("DELETE FROM medical_audit_log WHERE owner_user_id=?", (int(user_id),)); con.commit(); con.close()
    for path in paths:
        with contextlib.suppress(Exception): Path(path).unlink()


def _search_docs(mod: Any, user_id: int, query: str) -> list[dict]:
    q = _clean(query, 120).lower()
    if not q: return []
    profiles = {p["id"] for p in _profiles(mod, user_id)}; con = _connect(mod); rows = con.execute("SELECT id, profile_id, category, title, document_date, analysis_enc, metadata_enc, created_ts FROM medical_documents WHERE owner_user_id=? AND status='active' ORDER BY created_ts DESC LIMIT 200", (int(user_id),)).fetchall(); con.close(); result = []
    for row in rows:
        if row[1] not in profiles: continue
        hay = " ".join([row[3] or "", _dec(mod, row[5]), _dec(mod, row[6])]).lower()
        if q in hay: result.append({"id": row[0], "profile_id": row[1], "category": row[2], "title": row[3], "date": row[4], "created_ts": row[7]})
        if len(result) >= 15: break
    return result


def _pdf_font():
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        if Path(path).exists(): return path
    return ""


def _build_export_pdf(mod: Any, user_id: int, profile_id: int) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    font_name = "Helvetica"; font_path = _pdf_font()
    if font_path:
        font_name = "MedCardFont"
        with contextlib.suppress(Exception): pdfmetrics.registerFont(TTFont(font_name, font_path))
    styles = getSampleStyleSheet(); normal = ParagraphStyle("MedNormal", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=13, spaceAfter=5); heading = ParagraphStyle("MedHeading", parent=styles["Heading1"], fontName=font_name, fontSize=16, leading=20, spaceAfter=10); sub = ParagraphStyle("MedSub", parent=styles["Heading2"], fontName=font_name, fontSize=12, leading=15, spaceBefore=8, spaceAfter=6)
    bio = io.BytesIO(); doc = SimpleDocTemplate(bio, pagesize=A4, rightMargin=16*mm, leftMargin=16*mm, topMargin=16*mm, bottomMargin=16*mm); story = [Paragraph("Медицинская карта — экспорт для врача", heading), Paragraph(f"Профиль: {_profile_name(mod, user_id, profile_id)}", normal), Paragraph(f"Сформировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}", normal), Spacer(1, 8), Paragraph("Хронология документов", sub)]
    docs = _list_docs(mod, user_id, profile_id, "", 100)
    if not docs: story.append(Paragraph("Документы отсутствуют.", normal))
    for item in docs:
        row = _doc_row(mod, user_id, item["id"])
        if not row: continue
        meta = {}
        with contextlib.suppress(Exception): meta = json.loads(_dec(mod, row[12]) or "{}")
        story.append(Paragraph(f"{_fmt_date(row[5], row[13])} — {row[4]}".replace("&", "&amp;"), sub)); story.append(Paragraph((CATEGORY_LABELS.get(row[2], "Документ") + (f" · {row[3]}" if row[3] else "")).replace("&", "&amp;"), normal)); summary = _clean(meta.get("summary"), 1800).replace("&", "&amp;").replace("\n", "<br/>"); story.append(Paragraph(summary or "Краткая сводка отсутствует.", normal))
    story.extend([Spacer(1, 10), Paragraph("Важно", sub), Paragraph("Этот экспорт объединяет загруженные пользователем документы и справочные разборы ИИ. Он не является официальной медицинской картой клиники, диагнозом или назначением врача. Оригиналы документов доступны отдельно в Telegram-боте.", normal)]); doc.build(story); return bio.getvalue()


async def _offer_save(mod: Any, update: Any, context: Any) -> None:
    user = update.effective_user; uid = int(user.id)
    if not _eligible(mod, user):
        await update.effective_message.reply_text("📁 Персональная медицинская карта доступна в тарифах PRO и ULTIMATE. Сам медицинский разбор продолжает работать без карты.", reply_markup=_upgrade_kb(mod)); return
    if _auto_save(mod, uid) and _has_consent(mod, uid):
        ok, message, _ = await _save_pending(mod, update, context); await update.effective_message.reply_text(message, reply_markup=_card_main_kb(mod) if ok else _pending_save_kb(mod, uid)); return
    await update.effective_message.reply_text("📁 Сохранить оригинал, распознанные данные и этот разбор в медицинскую карту?", reply_markup=_pending_save_kb(mod, uid))


def _capture_from_context(context: Any) -> dict:
    cap = context.user_data.pop("medcard_source_capture", None) or {}; return cap if isinstance(cap, dict) else {}


def _pending_payload(track: str, goal: str | None, source_type: str, filename: str, mime_type: str, file_bytes: bytes, source_text: str, analysis: str) -> dict:
    return {"track": track, "goal": goal or "", "source_type": source_type, "filename": _safe_filename(filename), "mime_type": mime_type or "application/octet-stream", "file_bytes": bytes(file_bytes or b""), "source_text": _clean(source_text, 24000), "analysis": _clean(analysis, 30000), "created_ts": _now()}


async def _handle_medcard_callback(mod: Any, update: Any, context: Any, data: str) -> bool:
    if not data.startswith("medcard:"): return False
    q = update.callback_query
    with contextlib.suppress(Exception): await q.answer()
    user = update.effective_user; uid = int(user.id); action = data[len("medcard:"):]
    if action == "back_med": await q.message.edit_text(mod._medical_menu_text(), reply_markup=mod.medicine_kb()); return True
    if action == "open": await _show_card(mod, update, context, edit=True); return True
    if not _eligible(mod, user): await q.message.edit_text("🔒 Медицинская карта доступна только в PRO и ULTIMATE.", reply_markup=_upgrade_kb(mod)); return True
    if action == "consent_accept":
        _accept_consent(mod, uid)
        if context.user_data.get("medcard_pending"): await q.message.edit_text("✅ Медицинская карта создана. Теперь выберите профиль для сохранения нового документа.", reply_markup=_profile_select_kb(mod, uid, "save"))
        else: await _show_card(mod, update, context, edit=True)
        return True
    if not _has_consent(mod, uid): await _show_card(mod, update, context, edit=True); return True
    if action == "create_for_pending": await q.message.edit_text("Для сохранения сначала необходимо создать медицинскую карту и дать согласие на хранение чувствительных медицинских данных.", reply_markup=_consent_kb(mod)); return True
    if action == "discard_pending": context.user_data.pop("medcard_pending", None); await q.message.edit_text("Хорошо, этот разбор не сохранён.", reply_markup=mod.medicine_kb()); return True
    if action == "save_default":
        ok, message, doc_id = await _save_pending(mod, update, context); row = _doc_row(mod, uid, doc_id) if doc_id else None; await q.message.edit_text(message, reply_markup=_doc_kb(mod, doc_id, bool(row[9])) if ok and row else _card_main_kb(mod)); return True
    if action == "save_choose": await q.message.edit_text("К чьей медицинской карте относится документ?", reply_markup=_profile_select_kb(mod, uid, "save")); return True
    if action.startswith("save_profile:"):
        try: pid = int(action.rsplit(":", 1)[1])
        except Exception: pid = 0
        ok, message, doc_id = await _save_pending(mod, update, context, pid); row = _doc_row(mod, uid, doc_id) if doc_id else None; await q.message.edit_text(message, reply_markup=_doc_kb(mod, doc_id, bool(row[9])) if ok and row else _card_main_kb(mod)); return True
    if action == "summary": await _show_summary(mod, update); return True
    if action == "timeline": await _show_timeline(mod, update); return True
    if action.startswith("list:"): await _show_docs(mod, update, action.split(":", 1)[1]); return True
    if action == "meds": await _show_meds(mod, update); return True
    if action == "measurements": await _show_measurements(mod, update); return True
    if action == "profiles": await _show_profiles(mod, update); return True
    if action == "settings": await _show_settings(mod, update); return True
    if action == "search": context.user_data["medcard_wait"] = {"action": "search"}; await q.message.edit_text("🔎 Напишите слово или фразу для поиска по названиям, распознанным данным и разборам.", reply_markup=_kb(mod, [[("⬅️ К карте", "medcard:open")]])); return True
    if action == "profile_add": context.user_data["medcard_wait"] = {"action": "add_profile"}; await q.message.edit_text("➕ Напишите имя профиля, например: «Елена», «Ребёнок Алексей» или «Мама».", reply_markup=_kb(mod, [[("⬅️ К профилям", "medcard:profiles")]])); return True
    if action.startswith("profile_default:"):
        try: pid = int(action.rsplit(":", 1)[1])
        except Exception: pid = 0
        _set_default_profile(mod, uid, pid); await _show_card(mod, update, context, edit=True); return True
    if action.startswith("doc:"): await _show_doc(mod, update, action.split(":", 1)[1]); return True
    if action.startswith("analysis:"):
        doc_id = action.split(":", 1)[1]; row = _doc_row(mod, uid, doc_id)
        if not row: return True
        chunks = _chunk(_dec(mod, row[11])); await q.message.edit_text(chunks[0][:3900], reply_markup=_doc_kb(mod, doc_id, bool(row[9])))
        for part in chunks[1:]: await q.message.reply_text(part)
        _audit(mod, uid, "analysis_open", "document", doc_id); return True
    if action.startswith("original:"):
        doc_id = action.split(":", 1)[1]; row = _doc_row(mod, uid, doc_id)
        if not row: return True
        data_bytes = _read_encrypted_file(mod, row[9])
        if not data_bytes: await q.message.reply_text("Оригинальный файл не найден в хранилище."); return True
        bio = io.BytesIO(data_bytes); bio.name = _safe_filename(row[7] or "medical_document"); await q.message.reply_document(document=mod.InputFile(bio, filename=bio.name), caption=f"Оригинал: {row[4]}"); _audit(mod, uid, "original_open", "document", doc_id); return True
    if action.startswith("delete_ask:"):
        doc_id = action.split(":", 1)[1]; await q.message.edit_text("Удалить этот документ, оригинал и связанный разбор? Действие необратимо.", reply_markup=_kb(mod, [[("🗑 Да, удалить", f"medcard:delete_yes:{doc_id}")], [("⬅️ Отмена", f"medcard:doc:{doc_id}")]])); return True
    if action.startswith("delete_yes:"):
        doc_id = action.split(":", 1)[1]; ok = _delete_document(mod, uid, doc_id); await q.message.edit_text("✅ Документ удалён." if ok else "Документ не найден.", reply_markup=_card_main_kb(mod)); return True
    if action == "auto_toggle":
        new_value = 0 if _auto_save(mod, uid) else 1; con = _connect(mod); con.execute("UPDATE medical_consents SET auto_save=? WHERE user_id=?", (new_value, uid)); con.commit(); con.close(); _audit(mod, uid, "auto_save_toggle", "settings", str(new_value)); await _show_settings(mod, update); return True
    if action == "delete_all_ask": await q.message.edit_text("⚠️ Удалить всю медицинскую карту: все профили, документы, оригиналы, показатели и назначения? Восстановить данные будет невозможно.", reply_markup=_kb(mod, [[("🗑 Удалить всю карту", "medcard:delete_all_yes")], [("⬅️ Отмена", "medcard:settings")]])); return True
    if action == "delete_all_yes": _delete_all(mod, uid); context.user_data.pop("medcard_pending", None); await q.message.edit_text("✅ Медицинская карта и сохранённые данные удалены. Согласие отозвано.", reply_markup=mod.medicine_kb()); return True
    if action == "export":
        pid = _default_profile_id(mod, uid); await q.message.reply_text("📤 Формирую защищённую сводку PDF для врача…")
        try:
            pdf = await asyncio.to_thread(_build_export_pdf, mod, uid, pid); bio = io.BytesIO(pdf); bio.name = f"medical_card_{datetime.now().strftime('%Y%m%d')}.pdf"; await q.message.reply_document(document=mod.InputFile(bio, filename=bio.name), caption="Экспорт медицинской карты. Оригиналы документов в этот PDF не вложены."); _audit(mod, uid, "export_pdf", "profile", str(pid))
        except Exception as exc: await q.message.reply_text(f"Не удалось сформировать PDF: {type(exc).__name__}")
        return True
    return True


async def _handle_medcard_text(mod: Any, update: Any, context: Any, text: str) -> bool:
    state = context.user_data.get("medcard_wait") or {}; action = state.get("action") if isinstance(state, dict) else ""
    if not action: return False
    context.user_data.pop("medcard_wait", None); uid = int(update.effective_user.id)
    if not _eligible(mod, update.effective_user) or not _has_consent(mod, uid): await _show_card(mod, update, context); return True
    if action == "add_profile":
        ok, message = _add_profile(mod, uid, text); await update.effective_message.reply_text(("✅ Профиль создан: " if ok else "❌ ") + message, reply_markup=_profile_select_kb(mod, uid, "save") if context.user_data.get("medcard_pending") else _card_main_kb(mod)); return True
    if action == "search":
        rows = _search_docs(mod, uid, text)
        if not rows: await update.effective_message.reply_text("По вашему запросу ничего не найдено.", reply_markup=_card_main_kb(mod)); return True
        lines = [f"🔎 Результаты поиска: {text}", ""]; buttons = []
        for idx, item in enumerate(rows, 1): lines.append(f"{idx}. {_fmt_date(item['date'], item['created_ts'])} — {item['title']}"); buttons.append([(f"{idx}. {item['title'][:34]}", f"medcard:doc:{item['id']}")])
        buttons.append([("⬅️ К карте", "medcard:open")]); await update.effective_message.reply_text("\n".join(lines), reply_markup=_kb(mod, buttons)); return True
    return False


def _patch_plan_text(mod: Any) -> None:
    fn = getattr(mod, "_plan_card_text", None)
    if not callable(fn) or getattr(fn, "_medcard_wrapped", False): return
    def wrapped(key: str):
        text = fn(key); k = str(key or "").lower()
        if k in {"pro", "ultimate"} and "медицинская карта" not in text.lower(): text += "\n• 📁 Персональная медицинская карта: документы, хронология, показатели и экспорт врачу"
        elif k == "start" and "медицинская карта" not in text.lower(): text += "\n• Медицинские разборы доступны без постоянной медицинской карты"
        return text
    wrapped._medcard_wrapped = True; mod._plan_card_text = wrapped


def _runtime_main_module() -> Any | None:
    for name in ("__main__", "main"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "DB_PATH"): return mod
    return None


async def _entry_open(update, context):
    mod = _runtime_main_module()
    if mod is not None: await _show_card(mod, update, context)


async def _entry_callback(update, context):
    mod = _runtime_main_module()
    if mod is None: return
    data = (getattr(getattr(update, "callback_query", None), "data", "") or "").strip(); handled = await _handle_medcard_callback(mod, update, context, data)
    if handled:
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop


async def _entry_text(update, context):
    if not (context.user_data.get("medcard_wait") or {}): return
    mod = _runtime_main_module()
    if mod is None: return
    text = (getattr(getattr(update, "message", None), "text", "") or "").strip()
    if await _handle_medcard_text(mod, update, context, text):
        from telegram.ext import ApplicationHandlerStop
        raise ApplicationHandlerStop


async def _entry_capture_document(update, context):
    mod = _runtime_main_module()
    if mod is None or not getattr(update, "message", None) or not update.message.document: return
    doc = update.message.document; caption = (update.message.caption or "").strip(); should = False; fn = getattr(mod, "_should_route_medical", None)
    if callable(fn):
        with contextlib.suppress(Exception): should = bool(fn(context, update.effective_user.id, caption, doc.file_name or "file"))
    if not should: return
    try:
        tg_file = await doc.get_file(); raw = bytes(await tg_file.download_as_bytearray()); context.user_data["medcard_source_capture"] = {"file_bytes": raw, "filename": doc.file_name or "medical_document", "mime_type": doc.mime_type or "application/octet-stream"}
    except Exception: pass


def install_builder_hook() -> None:
    try: from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, MessageHandler, filters
    except Exception: return
    if getattr(ApplicationBuilder, "_medcard_v109_hooked", False): return
    original_build = ApplicationBuilder.build
    def build(self, *args, **kwargs):
        app = original_build(self, *args, **kwargs)
        if not getattr(app, "_medcard_v109_handlers", False):
            app.add_handler(CommandHandler("medcard", _entry_open), group=-4); app.add_handler(CallbackQueryHandler(_entry_callback, pattern=r"^medcard:"), group=-4); app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _entry_text), group=-4); app.add_handler(MessageHandler(filters.Document.ALL, _entry_capture_document), group=-4); setattr(app, "_medcard_v109_handlers", True)
        return app
    ApplicationBuilder.build = build; setattr(ApplicationBuilder, "_medcard_v109_hooked", True)


def patch_module(mod: Any) -> bool:
    if getattr(mod, PATCH_FLAG, False): mod.PATCH_VERSION = VERSION; return True
    required = ["medicine_kb", "on_cb", "on_text", "on_doc", "_medical_analyze_text", "_medical_analyze_image", "get_subscription_tier"]
    if not all(hasattr(mod, name) for name in required): return False
    if not str(getattr(mod, "MEDICAL_PATCH_VERSION", "")).startswith("v108"): return False
    _init_db(mod); old_medicine_kb = mod.medicine_kb
    def medicine_kb():
        base = old_medicine_kb()
        try:
            rows = [list(row) for row in base.inline_keyboard]; back = rows.pop() if rows else []; rows.append([mod.InlineKeyboardButton("📁 Моя медицинская карта · PRO/ULTIMATE", callback_data="medcard:open")]); rows.append(back) if back else None; return mod.InlineKeyboardMarkup(rows)
        except Exception: return old_medicine_kb()
    mod.medicine_kb = medicine_kb
    med108 = sys.modules.get("medical_v108_patch")
    if med108 is None: import medical_v108_patch as med108
    async def medical_analyze_text(update, context, text: str, goal: str | None = None):
        uid = int(update.effective_user.id); track = mod._mode_track_get(uid); await update.effective_message.reply_text("🩺 Читаю медицинский материал и готовлю подробный разбор с приоритетами, сроками и планом действий…"); answer = await med108._reason(mod, text, track, goal, "текст медицинского документа"); await med108._send_answer(mod, update, context, answer); capture = _capture_from_context(context); file_bytes = bytes(capture.get("file_bytes") or _clean(text).encode("utf-8")); filename = capture.get("filename") or "medical_text.txt"; mime = capture.get("mime_type") or "text/plain"; context.user_data["medcard_pending"] = _pending_payload(track, goal, "text", filename, mime, file_bytes, text, answer); await _offer_save(mod, update, context)
    async def medical_analyze_image(update, context, img_bytes: bytes, goal: str | None = None):
        uid = int(update.effective_user.id); track = mod._mode_track_get(uid); await update.effective_message.reply_text("🩺 Сначала точно считываю медицинский текст и показатели, затем отдельно проверю их смысл и приоритет…"); b64 = base64.b64encode(img_bytes).decode("ascii"); extracted = await mod.ask_openai_vision(med108._extraction_prompt(track, goal), b64, mod.sniff_image_mime(img_bytes)); extracted = med108._clean_text(extracted)
        if not extracted or extracted.lower().startswith("не удалось проанализировать"): answer = "Не удалось надёжно прочитать изображение. Сделайте фото строго сверху, без бликов и теней, либо загрузите PDF/текст заключения."
        else: await update.effective_message.reply_text("✅ Данные считаны. Формирую клинически значимый разбор без простого пересказа…"); answer = await med108._reason(mod, extracted, track, goal, "изображение медицинского документа")
        await med108._send_answer(mod, update, context, answer); capture = _capture_from_context(context); filename = capture.get("filename") or "medical_photo.jpg"; mime = capture.get("mime_type") or mod.sniff_image_mime(img_bytes); context.user_data["medcard_pending"] = _pending_payload(track, goal, "image", filename, mime, img_bytes, extracted, answer); await _offer_save(mod, update, context)
    mod._medical_analyze_text = medical_analyze_text; mod._medical_analyze_image = medical_analyze_image
    old_capability = getattr(mod, "_medical_capability_text", None)
    if callable(old_capability):
        def capability():
            text = old_capability(); return text if "медицинская карта" in text.lower() else text + "\n\n📁 В PRO и ULTIMATE доступна персональная медицинская карта: сохранение оригиналов, хронология, показатели, назначения, поиск и экспорт врачу."
        mod._medical_capability_text = capability
    _patch_plan_text(mod); mod.medical_card_db_init = lambda: _init_db(mod); mod.medical_card_open = lambda update, context: _show_card(mod, update, context); mod.MEDICAL_CARD_VERSION = VERSION; mod.PATCH_VERSION = VERSION; setattr(mod, PATCH_FLAG, True); return True


def install_async() -> None:
    def worker() -> None:
        for _ in range(4000):
            for name in ("__main__", "main"):
                mod = sys.modules.get(name)
                if mod is None: continue
                try:
                    if patch_module(mod): return
                except Exception: continue
            time.sleep(0.02)
    threading.Thread(target=worker, daemon=True, name="medical-card-v109-patcher").start()
