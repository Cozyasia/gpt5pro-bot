# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

Celebrity Selfie is a normal, directly registered feature in ``main.py``.
No historical selfie overlays, builder monkey patches, or runtime stampers are
loaded here.

Render Blueprint disk declarations do not attach a disk to every already
existing service automatically.  A manual deploy can therefore start without a
writable ``/data`` mount.  Resolve the Celebrity Selfie storage directory before
``main.py`` is imported so the bot stays online.  When the persistent disk is
available, ``/data/celebrity_selfie`` remains the first choice; otherwise the
feature uses a writable temporary runtime directory and reports it in
``/version``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".neyrobot_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _select_celebrity_selfie_data_dir() -> str:
    requested = Path(
        os.environ.get("CELEBRITY_SELFIE_DATA_DIR", "/data/celebrity_selfie")
    ).expanduser()
    fallbacks = [
        Path(tempfile.gettempdir()) / "neyrobot" / "celebrity_selfie",
        Path.cwd() / ".runtime" / "celebrity_selfie",
    ]

    seen: set[str] = set()
    for candidate in [requested, *fallbacks]:
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if _is_writable_directory(candidate):
            os.environ["CELEBRITY_SELFIE_DATA_DIR"] = normalized
            if candidate != requested:
                print(
                    "[neyrobot-storage] requested Celebrity Selfie storage is not "
                    f"writable: {requested}; using runtime fallback: {candidate}"
                )
            return normalized

    # ``tempfile.gettempdir()`` should be writable on Render.  Keep a final
    # explicit value so diagnostics remain deterministic even on an unusual
    # host where every probe failed.
    emergency = str(Path(tempfile.gettempdir()) / "neyrobot_celebrity_selfie")
    os.environ["CELEBRITY_SELFIE_DATA_DIR"] = emergency
    print(f"[neyrobot-storage] no writable storage probe succeeded; using {emergency}")
    return emergency


_select_celebrity_selfie_data_dir()

try:
    from neyrobot_prod.bootstrap import install_early as install_production_early
    install_production_early()
except Exception as exc:
    print(f"[neyrobot-prod] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_early as install_version_contract_early
    install_version_contract_early()
except Exception as exc:
    print(f"[neyrobot-version] early bootstrap warning: {type(exc).__name__}: {exc}")
