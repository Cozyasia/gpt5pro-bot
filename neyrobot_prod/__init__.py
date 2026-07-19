# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v129-celebrity-selfie-writable-reference-library-2026-07-19"

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

# Keep the audited v122 catalog/reference/generation runtime. Telegram routing
# remains disabled in the historical module.
try:
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_library_runtime
    _install_celebrity_library_runtime()
except Exception:
    pass

# v129 is the sole Telegram owner and verifies both independent writable roots:
# per-user sessions and the downloaded celebrity reference library.
try:
    from celebrity_selfie_v129 import install_builder_hook as _install_celebrity_selfie_references
    _install_celebrity_selfie_references()
except Exception:
    pass

__all__ = ["VERSION"]
