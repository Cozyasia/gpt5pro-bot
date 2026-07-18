# -*- coding: utf-8 -*-
"""Neyro-Bot production hardening package."""

VERSION = "v120.0-medical-progressive-ui-2026-07-18"

# The package is imported by secret_loader before main.py builds the Telegram
# application. Register the progressive medical-answer callback route here so
# it cannot lose a startup race against legacy runtime overlays.
try:
    from .medical_answer_ui import install_early as _install_medical_answer_ui
    _install_medical_answer_ui()
except Exception:
    pass

__all__ = ["VERSION"]
