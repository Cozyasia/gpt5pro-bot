# -*- coding: utf-8 -*-
"""Install the repository root on sys.path before Python imports sitecustomize.

Render starts the service with `python -u main.py`. The production selfie runtime
is activated from sitecustomize.py; installing this repository in editable mode
makes that module discoverable during Python's normal site initialization, before
main.py registers Telegram handlers.
"""
from setuptools import find_packages, setup

setup(
    name="neyrobot-runtime-bootstrap",
    version="0.0.0",
    description="Runtime bootstrap for Neyro-Bot production overlays",
    packages=find_packages(include=["neyrobot_prod", "neyrobot_prod.*"]),
    py_modules=["sitecustomize"],
)
