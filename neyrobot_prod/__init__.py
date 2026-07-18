# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v125-celebrity-selfie-single-owner-2026-07-19"

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

# Keep the v122 catalog, licensed-reference synchronizer and generation engine.
# Its public commands remain available, while v125 preempts its conversation
# callbacks before they can reach the old name-only/photo-workshop routes.
try:
    from celebrity_selfie_v122 import install_builder_hook as _install_celebrity_selfie_base
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_selfie_runtime
    _install_celebrity_selfie_base()
    _install_celebrity_selfie_runtime()
except Exception:
    pass

# Do NOT install v123, v123_pedit or v124 builder hooks here. They are retained
# only as implementation libraries for backward-compatible helper functions.
# Register exactly one conversation owner at the earliest private group.
try:
    from celebrity_selfie_v125 import install_builder_hook as _install_celebrity_selfie_single_owner
    _install_celebrity_selfie_single_owner()
except Exception:
    pass

__all__ = ["VERSION"]
