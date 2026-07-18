# -*- coding: utf-8 -*-
"""Automatically load Neyro-Bot production hardening before main.py."""

try:
    from neyrobot_prod.bootstrap import install_early as install_production_early

    install_production_early()
except Exception as exc:  # startup must remain available for diagnostics
    print(f"[neyrobot-prod] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_early as install_version_contract_early

    install_version_contract_early()
except Exception as exc:  # a stale version label must never block bot startup
    print(f"[neyrobot-version] early bootstrap warning: {type(exc).__name__}: {exc}")
