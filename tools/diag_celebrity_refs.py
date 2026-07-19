# -*- coding: utf-8 -*-
import asyncio
import inspect
import json
import os
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CELEBRITY_SESSION_ROOT", "/tmp/celebrity_selfie_sessions")

import celebrity_selfie_v128 as feature


class Message:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append({"text": text, "markup": type(reply_markup).__name__ if reply_markup else None})
        return SimpleNamespace()


class Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.bot = SimpleNamespace()


def safe_repr(value, limit=3000):
    try:
        return repr(value)[:limit]
    except Exception as exc:
        return f"<repr failed: {exc!r}>"


def engine_storage_inventory():
    found = {}
    lib_cls = getattr(feature.engine, "CelebrityLibrary", None)
    if lib_cls is not None:
        found["CelebrityLibrary:signature"] = safe_repr(inspect.signature(lib_cls))
        found["CelebrityLibrary:init_signature"] = safe_repr(inspect.signature(lib_cls.__init__))
        found["CelebrityLibrary:class_dict"] = {
            name: {"type": type(value).__name__, "repr": safe_repr(value, 1000)}
            for name, value in vars(lib_cls).items()
            if not name.startswith("__")
        }

    for name, value in vars(feature.engine).items():
        rendered = safe_repr(value)
        cls_name = type(value).__name__
        if (
            "/data" in rendered
            or "celebrity_library" in rendered
            or "CELEBRITY" in name.upper()
            or cls_name == "CelebrityLibrary"
        ):
            row = {"type": cls_name, "repr": rendered}
            if cls_name == "CelebrityLibrary":
                row["dict"] = {k: safe_repr(v) for k, v in vars(value).items()}
            found[name] = row

    for fn_name in ("materialize_layout", "ensure_refs", "_prepare_library_refs"):
        fn = getattr(feature.engine, fn_name, None)
        if callable(fn):
            try:
                found[f"signature:{fn_name}"] = str(inspect.signature(fn))
            except Exception as exc:
                found[f"signature:{fn_name}"] = repr(exc)
    return found


async def probe(name: str):
    message = Message()
    update = SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=129001),
        effective_chat=SimpleNamespace(id=129001),
    )
    context = Context()
    session = feature.core._new_session(context)
    user_photo = Path(tempfile.gettempdir()) / "diag_user_selfie.jpg"
    user_photo.write_bytes(b"not-a-real-image-but-path-exists")
    session["user_photo_path"] = str(user_photo)
    session["state"] = "choose_celebrity"

    results = feature.engine.search_catalog(name, 10)
    if not results:
        raise RuntimeError(f"catalog lookup failed for {name!r}")
    item = results[0]
    await asyncio.wait_for(
        feature.engine._prepare_library_refs(update, context, item),
        timeout=120,
    )
    return {
        "name": name,
        "item": item,
        "session": dict(feature.core._session(context, create=False)),
        "messages": message.sent,
    }


async def main_async():
    output = {"inventory": engine_storage_inventory(), "probes": []}
    for name in ("Роман Абрамович", "Тимур Батрутдинов"):
        try:
            output["probes"].append({"ok": True, "result": await probe(name)})
        except BaseException:
            output["probes"].append({"ok": False, "name": name, "traceback": traceback.format_exc()})
    Path("celebrity-refs-diagnostic.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    if not all(row.get("ok") for row in output["probes"]):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main_async())
