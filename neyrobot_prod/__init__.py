# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v127-celebrity-selfie-exact-integration-2026-07-19"

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

# Keep only the audited v122 library runtime: 50 RU + 50 US catalog entries,
# Wikimedia reference packs and the multi-image generation/refinement engine.
try:
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_library_runtime
    _install_celebrity_library_runtime()
except Exception:
    pass

# v127 owns the exact production callbacks and media/text routing. Older
# Celebrity Selfie builder hooks are deliberately not installed.
try:
    from celebrity_selfie_v127 import install_builder_hook as _install_celebrity_selfie_exact
    _install_celebrity_selfie_exact()
except Exception:
    pass

__all__ = ["VERSION"]
