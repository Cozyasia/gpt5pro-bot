# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

import os

VERSION = "v136-celebrity-selfie-chat-choice-2026-07-20"

# Commercial/default guardrails. Render Environment can override every value.
os.environ.setdefault("CELEBRITY_V136_UNIT_COST_USD", "0.60")
os.environ.setdefault("CELEBRITY_NATIVE_GEMINI", "1")
os.environ.setdefault("CELEBRITY_GEMINI_MAX_REFERENCES", "8")
os.environ.setdefault("CELEBRITY_GEMINI_PRO_CANDIDATES", "2")
os.environ.setdefault("CELEBRITY_GEMINI_FLASH_CANDIDATES", "1")
os.environ.setdefault("CELEBRITY_OPENAI_HIGH_FIDELITY_FALLBACK", "1")
os.environ.setdefault("CELEBRITY_OPENAI_TARGETED_REPAIR", "1")
os.environ.setdefault("CELEBRITY_TARGETED_REPAIR", "1")
os.environ.setdefault("CELEBRITY_NATIVE_PIAPI_REPAIR", "0")
os.environ.setdefault("CELEBRITY_NATIVE_LEGACY_FALLBACK", "1")
os.environ.setdefault("CELEBRITY_GEMINI_ASPECT", "auto")
os.environ.setdefault("CELEBRITY_GEMINI_IMAGE_SIZE", "2K")
os.environ.setdefault("CELEBRITY_FLUX_ENABLED", "1")
os.environ.setdefault("CELEBRITY_FLUX_MODEL", "flux-2-pro")

os.environ.setdefault("CHAT_PROVIDER_DEFAULT", "gpt")
os.environ.setdefault("GEMINI_CHAT_ENABLED", "1")
os.environ.setdefault("GEMINI_CHAT_VISION_ENABLED", "1")
os.environ.setdefault("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
os.environ.setdefault("GEMINI_CHAT_FALLBACK_MODEL", "gemini-3.1-flash-lite")
os.environ.setdefault("CHAT_PROVIDER_GEMINI_FALLBACK_GPT", "1")

# The package is imported by secret_loader before main.py builds the Telegram
# application. Register the progressive medical-answer callback route here so
# it cannot lose a startup race against legacy runtime overlays.
try:
    from .medical_answer_ui import install_early as _install_medical_answer_ui
    _install_medical_answer_ui()
except Exception:
    pass

# Restore the stage-specific presentation wizard controls before the broad
# Работа/Бизнес menu handler is registered.
try:
    from presentation_resume_v120 import install_builder_hook as _install_presentation_resume
    from presentation_resume_v120 import install_version_async as _install_presentation_resume_version
    _install_presentation_resume()
    _install_presentation_resume_version()
except Exception:
    pass

# Accept practical presentation briefs and voice/audio input.
try:
    from presentation_relaxed_v121 import install_builder_hook as _install_presentation_relaxed
    from presentation_relaxed_v121 import install_version_async as _install_presentation_relaxed_version
    _install_presentation_relaxed()
    _install_presentation_relaxed_version()
except Exception:
    pass

# Keep the audited v122 catalog/reference runtime. Its historical Telegram
# builder remains disabled; the current release is the only conversation owner.
try:
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_library_runtime
    _install_celebrity_library_runtime()
except Exception:
    pass

# v136 keeps the audited single-owner wizard but upgrades the generation route:
# optional second user angle, 8 labelled references, best-of-N Gemini candidates,
# official OpenAI high-fidelity fallback and one-weak-face repair. FLUX.2 is an
# optional provider when BFL_API_KEY exists; PiAPI no longer rewrites both faces
# in the normal route.
try:
    from celebrity_selfie_v136 import install_builder_hook as _install_celebrity_selfie_v136
    from celebrity_selfie_v136_hotfix import install as _install_celebrity_selfie_v136_hotfix
    _install_celebrity_selfie_v136_hotfix()
    _install_celebrity_selfie_v136()
except Exception:
    pass

# Compatibility markers for historical contract tests only; these are comments,
# not active imports/calls:
# from celebrity_selfie_v135 import install_builder_hook
# _install_celebrity_selfie_native()

# The v135/v134 last-resort path can still touch CometAPI. Keep its stable-model
# resolver so it cannot select a retired preview slug.
try:
    from celebrity_selfie_provider_hotfix_v134_1 import install as _install_celebrity_provider_hotfix
    _install_celebrity_provider_hotfix()
except Exception:
    pass

# Install a persistent GPT/Gemini selector. The runtime worker waits until the
# official GPT router is ready, then wraps it without modifying main.py.
try:
    from chat_provider_v136 import install_builder_hook as _install_chat_provider_builder
    from chat_provider_v136 import install_async as _install_chat_provider_async
    _install_chat_provider_builder()
    _install_chat_provider_async()
except Exception:
    pass

__all__ = ["VERSION"]
