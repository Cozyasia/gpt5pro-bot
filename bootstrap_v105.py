# -*- coding: utf-8 -*-
"""Render entry point for Presentation Studio v105."""
from __future__ import annotations

import runpy

from presentation_v105_patch import install_import_hook, patch_main_version_async

install_import_hook()
patch_main_version_async()
runpy.run_path("main.py", run_name="__main__")
