# -*- coding: utf-8 -*-
"""Neyro-Bot production defaults.

The Celebrity Selfie feature is owned directly by ``main.py`` and
``celebrity_selfie_mode.py``. Historical celebrity-selfie overlays are not
imported from this package.
"""

import os

VERSION = "v200-celebrity-selfie-clean-rewrite-2026-07-24"

os.environ.setdefault("CHAT_PROVIDER_DEFAULT", "gpt")
os.environ.setdefault("GEMINI_CHAT_ENABLED", "1")
os.environ.setdefault("GEMINI_CHAT_VISION_ENABLED", "1")
os.environ.setdefault("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
os.environ.setdefault("GEMINI_CHAT_FALLBACK_MODEL", "gemini-3.1-flash-lite")
os.environ.setdefault("CHAT_PROVIDER_GEMINI_FALLBACK_GPT", "1")

try:
    from .medical_answer_ui import install_early as _install_medical_answer_ui
    _install_medical_answer_ui()
except Exception:
    pass

try:
    from presentation_resume_v120 import install_builder_hook as _install_presentation_resume
    _install_presentation_resume()
except Exception:
    pass

try:
    from presentation_relaxed_v121 import install_builder_hook as _install_presentation_relaxed
    _install_presentation_relaxed()
except Exception:
    pass

try:
    from chat_provider_v136 import install_builder_hook as _install_chat_provider_builder
    from chat_provider_v136 import install_async as _install_chat_provider_async
    _install_chat_provider_builder()
    _install_chat_provider_async()
except Exception:
    pass

try:
    from ui_hotfix_v137 import install_builder_hook as _install_ui_v137_builder
    from ui_hotfix_v137 import install_runtime_patches as _install_ui_v137_runtime
    _install_ui_v137_runtime()
    _install_ui_v137_builder()
except Exception:
    pass

__all__ = ["VERSION"]
