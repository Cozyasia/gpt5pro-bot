# -*- coding: utf-8 -*-
"""Automatically load Neyro-Bot production hardening before main.py."""

try:
    from neyrobot_prod.bootstrap import install_early
    from neyrobot_prod.celebrity_selfie import install_async as install_celebrity_selfie
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner

    install_early()
    install_version_owner()
    install_celebrity_selfie()
except Exception as exc:  # startup must remain available for diagnostics
    print(f"[neyrobot-prod] early bootstrap warning: {type(exc).__name__}: {exc}")
