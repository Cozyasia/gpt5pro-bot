# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v126-celebrity-selfie-clean-rewrite-2026-07-19"

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

# Import the audited v122 catalog/reference/generation engine and retain its
# background library preparation. Its Telegram builder hook is intentionally
# NOT installed: v126 is the sole owner of every Celebrity Selfie update.
try:
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_library_runtime
    _install_celebrity_library_runtime()
except Exception:
    pass

# Completely rewritten single Telegram wizard. v123, v123_pedit, v124 and v125
# remain only as historical source files and are not registered at runtime.
try:
    from celebrity_selfie_v126 import install_builder_hook as _install_celebrity_selfie_clean
    _install_celebrity_selfie_clean()
except Exception:
    pass

__all__ = ["VERSION"]
