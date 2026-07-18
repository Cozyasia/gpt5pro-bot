# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v124-celebrity-selfie-telegram-photo-flow-2026-07-19"

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

# Exact-identity Celebrity Selfie base: 50+50 catalog, licensed references,
# custom references and resemblance refinement.
try:
    from celebrity_selfie_v122 import install_builder_hook as _install_celebrity_selfie
    from celebrity_selfie_v122 import install_runtime_async as _install_celebrity_selfie_runtime
    _install_celebrity_selfie()
    _install_celebrity_selfie_runtime()
except Exception:
    pass

# v123 protects the library flow from legacy photo/text handlers.
try:
    from celebrity_selfie_v123 import install_builder_hook as _install_celebrity_selfie_flow
    from celebrity_selfie_v123 import install_runtime_async as _install_celebrity_selfie_flow_runtime
    _install_celebrity_selfie_flow()
    _install_celebrity_selfie_flow_runtime()
except Exception:
    pass

# Compatibility bridge for the quick-action callback pedit:aiselfie.
try:
    from celebrity_selfie_v123_pedit import install_builder_hook as _install_celebrity_selfie_pedit
    _install_celebrity_selfie_pedit()
except Exception:
    pass

# v124 is the final owner of the complete wizard at priority -20000. It starts
# without recovery/error cards, accepts ordinary Telegram photos and image
# documents, advances directly to celebrity selection and stops every legacy
# photo router while the session is active.
try:
    from celebrity_selfie_v124 import install_builder_hook as _install_celebrity_selfie_telegram_photo
    _install_celebrity_selfie_telegram_photo()
except Exception:
    pass

__all__ = ["VERSION"]
