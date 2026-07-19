# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v132-celebrity-selfie-validated-final-output-2026-07-19"

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

# v132 retains v131's tolerant input preflight and replaces the generation
# pipeline with face-only scene inputs, explicit PiAPI output parsing, strict
# collage/scene validation, duplicate-job protection and stale-result blocking.
try:
    from celebrity_selfie_v132 import install_builder_hook as _install_celebrity_selfie_validated_output
    _install_celebrity_selfie_validated_output()
except Exception:
    pass

__all__ = ["VERSION"]
