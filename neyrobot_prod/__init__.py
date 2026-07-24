# -*- coding: utf-8 -*-
"""Neyro-Bot production defaults.

v161 preserves the complete v160 payment, selfie-routing, medical-integrity and
four-candidate release, while restoring the proven PiAPI celebrity-lock and
original-user-pixel composite route for Roman Abramovich.
Historical modules remain implementation libraries rather than competing owners.
"""

import os

VERSION = "v161-roman-hybrid-identity-2026-07-24"

# Current Celebrity Selfie production contract.
os.environ.setdefault("CELEBRITY_V156_UNIT_COST_USD", "0.80")
os.environ.setdefault("CELEBRITY_V156_CANDIDATES", "4")
os.environ.setdefault("CELEBRITY_V156_COMET_ROUTES", "gemini,openai-edit")
os.environ.setdefault("CELEBRITY_V156_COMET_GEMINI_MODELS", "gemini-2.5-flash-image,gemini-3-pro-image")
os.environ.setdefault("CELEBRITY_V156_TARGETED_REPAIR", "1")
os.environ.setdefault("CELEBRITY_V156_REFERENCE_VISION_QC", "1")
os.environ.setdefault("CELEBRITY_V156_VISION_QC", "1")
os.environ.setdefault("CELEBRITY_V156_MAX_CONCURRENCY", "1")
os.environ.setdefault("CELEBRITY_V157_MIN_USER_SIMILARITY", "64")
os.environ.setdefault("CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "70")
os.environ["CELEBRITY_V157_MIN_CELEBRITY_SIMILARITY"] = os.environ.get("CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "70")
os.environ["CELEBRITY_V156_MIN_USER_SIMILARITY"] = os.environ.get("CELEBRITY_V157_MIN_USER_SIMILARITY", "64")
os.environ["CELEBRITY_V156_MIN_CELEBRITY_SIMILARITY"] = os.environ.get("CELEBRITY_V158_MIN_CELEBRITY_SIMILARITY", "70")
os.environ.setdefault("CELEBRITY_V156_MIN_QUALITY", "62")
os.environ.setdefault("CELEBRITY_V156_EARLY_ACCEPT_TOTAL", "80")
os.environ.setdefault("CELEBRITY_V156_CELEBRITY_REFERENCE_LIMIT", "3")
os.environ.setdefault("CELEBRITY_FIXED_REF_CACHE", "/tmp/neyrobot_fixed_refs")

# v161 hybrid settings. The user's real pixels are segmented by PhotoRoom and
# Roman's identity is locked with PiAPI; v160 remains the safe fallback.
os.environ.setdefault("CELEBRITY_V145_CELEBRITY_PROVIDERS", "piapi,openai")
os.environ.setdefault("CELEBRITY_V145_PIAPI_MODES", "face-swap,multi-face-swap")
os.environ.setdefault("CELEBRITY_V145_PIAPI_REFERENCE_ATTEMPTS", "3")
os.environ.setdefault("CELEBRITY_V143_CUTOUT_PROVIDERS", "photoroom")
os.environ.setdefault("CELEBRITY_V143_MIN_VISUAL_NATURALNESS", "66")

# Explicitly disable obsolete generic fallbacks. PhotoRoom segmentation used by
# v161 and the independent background-removal feature remain enabled.
os.environ["CELEBRITY_V142_LOCAL_REMBG_FALLBACK"] = "0"
os.environ["CELEBRITY_V142_LEGACY_FALLBACK"] = "0"
os.environ["CELEBRITY_V143_LEGACY_FALLBACK"] = "0"
os.environ["CELEBRITY_V141_OPENAI_QUALITY_CLEANUP"] = "0"
os.environ["CELEBRITY_NATIVE_LEGACY_FALLBACK"] = "0"
os.environ["CELEBRITY_NATIVE_PIAPI_REPAIR"] = "0"
os.environ["CELEBRITY_V139_ONE_SHOT_FALLBACK"] = "0"

# General bot defaults unrelated to Celebrity Selfie.
os.environ.setdefault("CHAT_PROVIDER_DEFAULT", "gpt")
os.environ.setdefault("GEMINI_CHAT_ENABLED", "1")
os.environ.setdefault("GEMINI_CHAT_VISION_ENABLED", "1")
os.environ.setdefault("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
os.environ.setdefault("GEMINI_CHAT_FALLBACK_MODEL", "gemini-3.1-flash-lite")
os.environ.setdefault("CHAT_PROVIDER_GEMINI_FALLBACK_GPT", "1")

# Register non-selfie production features that rely on package import effects.
try:
    from .medical_answer_ui import install_early as _install_medical_answer_ui
    _install_medical_answer_ui()
except Exception:
    pass

try:
    from presentation_resume_v120 import install_builder_hook as _install_presentation_resume
    from presentation_resume_v120 import install_version_async as _install_presentation_resume_version
    _install_presentation_resume()
    _install_presentation_resume_version()
except Exception:
    pass

try:
    from presentation_relaxed_v121 import install_builder_hook as _install_presentation_relaxed
    from presentation_relaxed_v121 import install_version_async as _install_presentation_relaxed_version
    _install_presentation_relaxed()
    _install_presentation_relaxed_version()
except Exception:
    pass

try:
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_library_runtime
    _install_celebrity_library_runtime()
except Exception:
    pass

try:
    from chat_provider_v136 import install_builder_hook as _install_chat_provider_builder
    from chat_provider_v136 import install_async as _install_chat_provider_async
    _install_chat_provider_builder()
    _install_chat_provider_async()
except Exception:
    pass

# UI compatibility remains active; v161 is the final routing owner.
try:
    from ui_hotfix_v137 import install_builder_hook as _install_ui_v137_builder
    from ui_hotfix_v137 import install_runtime_patches as _install_ui_v137_runtime
    _install_ui_v137_runtime()
    _install_ui_v137_builder()
except Exception:
    pass

try:
    from ui_selfie_v138 import install_builder_hook as _install_v138_builder
    from ui_selfie_v138 import install_async as _install_v138_async
    from ui_selfie_v138_compat import install_builder_hook as _install_v138_compat_builder
    from ui_selfie_v138_compat import _safe_install_runtime_patches as _install_v138_safe_runtime
    _install_v138_safe_runtime()
    _install_v138_builder()
    _install_v138_compat_builder()
    _install_v138_async()
except Exception:
    pass

__all__ = ["VERSION"]
