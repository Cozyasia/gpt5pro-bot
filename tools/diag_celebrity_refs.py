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
os.environ.setdefault("CELEBRITY_LIBRARY_ROOT", "/tmp/celebrity_library")

import celebrity_selfie_v129 as feature


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
    found = {
        "selected_library_root": str(feature.engine.LIBRARY.root),
        "selected_library_writable": bool(feature._probe_writable(Path(feature.engine.LIBRARY.root))),
    }
    lib_cls = getattr(feature.engine, "CelebrityLibrary", None)
    if lib_cls is not None:
        found["CelebrityLibrary:signature"] = safe_repr(inspect.signature(lib_cls))
        found["CelebrityLibrary:init_signature"] = safe_repr(inspect.signature(lib_cls.__init__))
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
    await asyncio.wait_for(feature.engine._prepare_library_refs(update, context, item), timeout=120)
    paths = list(feature.engine.LIBRARY.reference_paths(item))
    return {
        "name": name,
        "item": item,
        "session": dict(feature.core._session(context, create=False)),
        "messages": message.sent,
        "reference_paths": [str(path) for path in paths],
        "reference_count": len(paths),
        "reference_sizes": [path.stat().st_size for path in paths],
    }


async def main_async():
    output = {"inventory": engine_storage_inventory(), "probes": []}
    for name in ("Роман Абрамович", "Тимур Батрутдинов"):
        try:
            output["probes"].append({"ok": True, "result": await probe(name)})
        except BaseException:
            output["probes"].append({"ok": False, "name": name, "traceback": traceback.format_exc()})
    Path("celebrity-refs-diagnostic.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    # The catalog flow is valid when Roman reaches the scene step; Timur may
    # legitimately require manual references, which is handled by v129.
    roman = output["probes"][0]
    if not roman.get("ok") or roman["result"].get("reference_count", 0) < 3:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main_async())
