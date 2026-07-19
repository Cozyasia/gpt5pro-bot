# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v133-celebrity-selfie-best-of-n-fallback-2026-07-19"

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

# v133 keeps v132's fail-closed final-output validation and adds production
# best-of-N candidates, a second scene provider fallback, scene-specific prompt
# contracts, face-similarity ranking, one actionable failure card and same-scene
# retry without repeating the whole wizard.
try:
    from celebrity_selfie_v133 import install_builder_hook as _install_celebrity_selfie_best_of_n
    _install_celebrity_selfie_best_of_n()
except Exception:
    pass

__all__ = ["VERSION"]
