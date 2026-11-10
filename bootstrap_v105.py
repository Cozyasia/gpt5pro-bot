# -*- coding: utf-8 -*-
"""Render entry point for Presentation Studio v105."""
from __future__ import annotations

import runpy

from presentation_v105_patch import install_import_hook, patch_main_version_async
from presentation_short_deck_patch import install_after_v105

install_import_hook()
install_after_v105()
patch_main_version_async()
runpy.run_path("main.py", run_name="__main__")
