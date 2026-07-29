# -*- coding: utf-8 -*-
"""Production bootstrap for Neyro-Bot.

Before ``main.py`` is executed, the obsolete Celebrity/Star AI-selfie source is
removed deterministically. This prevents the old monolith from restoring its
menus and callback handlers even when historical overlay modules are absent.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _purge_legacy_ai_selfie() -> None:
    target = Path(sys.argv[0] or "").resolve()
    if target.name != "main.py" or not target.is_file():
        return
    script = Path(__file__).resolve().parent / "tools" / "purge_legacy_ai_selfie.py"
    if not script.is_file():
        raise RuntimeError(f"purge script is missing: {script}")
    spec = importlib.util.spec_from_file_location("_neyrobot_purge_legacy_ai_selfie", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load legacy AI-selfie purge script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    removed = int(module.purge_file(target))
    print(f"[neyrobot-prod] AI_SELFIE_SOURCE_PURGED removed_nodes={removed}", flush=True)


try:
    _purge_legacy_ai_selfie()
except Exception as exc:
    print(f"[neyrobot-prod] FATAL legacy AI-selfie purge error: {type(exc).__name__}: {exc}", flush=True)
    raise

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}", flush=True)
