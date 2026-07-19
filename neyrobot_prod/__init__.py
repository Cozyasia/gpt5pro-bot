# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v134-celebrity-selfie-face-first-soft-scene-2026-07-19"

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

# v134 keeps v133 best-of-N generation and provider fallback, but changes the
# acceptance policy to face-first: background/location is a soft ranking signal,
# while only broken composition, missing second person, collage/split-screen or
# failed identity preservation can block delivery. One rescue scene is attempted
# when the environment is weak, but a good two-face result is no longer discarded
# solely because a landmark is subtle.
try:
    from celebrity_selfie_v134 import install_builder_hook as _install_celebrity_selfie_face_first
    _install_celebrity_selfie_face_first()
except Exception:
    pass

# CometAPI retired the old preview image route still present in the Render
# environment. Install the stable-model resolver after v134 has loaded so every
# scene candidate uses gemini-2.5-flash-image and never the dead preview slug.
try:
    from celebrity_selfie_provider_hotfix_v134_1 import install as _install_celebrity_provider_hotfix
    _install_celebrity_provider_hotfix()
except Exception:
    pass

__all__ = ["VERSION"]
