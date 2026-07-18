# -*- coding: utf-8 -*-
"""Automatically load Neyro-Bot production hardening before main.py."""

try:
    from neyrobot_prod.bootstrap import install_early

    install_early()
except Exception as exc:  # startup must remain available for diagnostics
    print(f"[neyrobot-prod] early bootstrap warning: {type(exc).__name__}: {exc}")
