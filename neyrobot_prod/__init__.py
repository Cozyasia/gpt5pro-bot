# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v122-celebrity-selfie-library-2026-07-19"

# The package is imported by secret_loader before main.py builds the Telegram
# application. Register the progressive medical-answer callback route here so
# it cannot lose a startup race against legacy runtime overlays.
try:
    from .medical_answer_ui import install_early as _install_medical_answer_ui
    _install_medical_answer_ui()
except Exception:
    pass

# Restore the stage-specific presentation wizard controls before the broad
# Работа/Бизнес menu handler is registered. This prevents an active project
# from becoming a text-only dead end after a restart.
try:
    from presentation_resume_v120 import install_builder_hook as _install_presentation_resume
    from presentation_resume_v120 import install_version_async as _install_presentation_resume_version
    _install_presentation_resume()
    _install_presentation_resume_version()
except Exception:
    pass

# Accept practical briefs without demanding artificial commercial sections,
# intercept the final build before the legacy strict preflight and allow the
# main presentation brief to be dictated by voice/audio.
try:
    from presentation_relaxed_v121 import install_builder_hook as _install_presentation_relaxed
    from presentation_relaxed_v121 import install_version_async as _install_presentation_relaxed_version
    _install_presentation_relaxed()
    _install_presentation_relaxed_version()
except Exception:
    pass

# Replace the old name-only AI-selfie path with one exact-identity mode:
# curated 50+50 catalog, licensed reference synchronization, custom reference
# upload and a second resemblance-refinement pass.
try:
    from celebrity_selfie_v122 import install_builder_hook as _install_celebrity_selfie
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_selfie_runtime
    _install_celebrity_selfie()
    _install_celebrity_selfie_runtime()
except Exception:
    pass

__all__ = ["VERSION"]
