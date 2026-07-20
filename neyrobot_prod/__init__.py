# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v135-celebrity-selfie-gemini3-native-identity-2026-07-20"

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

# v135 creates the final photograph natively with the current Gemini 3 image
# models and labelled identity references. PiAPI is only a selective repair;
# the audited v134 route remains available internally as a last-resort fallback.
try:
    from celebrity_selfie_v135 import install_builder_hook as _install_celebrity_selfie_native
    _install_celebrity_selfie_native()
except Exception:
    pass

# The v134 fallback still uses CometAPI. Keep its stable-model resolver so a
# fallback can never select the retired Gemini 2.5 preview slug.
try:
    from celebrity_selfie_provider_hotfix_v134_1 import install as _install_celebrity_provider_hotfix
    _install_celebrity_provider_hotfix()
except Exception:
    pass

__all__ = ["VERSION"]
