# -*- coding: utf-8 -*-
"""Load independent Neyro-Bot runtime layers before main.py."""

try:
    from neyrobot_prod.bootstrap import install_early

    install_early()
except Exception as exc:  # production bootstrap must remain diagnosable
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner

    install_version_owner()
except Exception as exc:  # stale /version must not block bot startup
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.celebrity_selfie import install_async as install_celebrity_selfie

    install_celebrity_selfie()
except Exception as exc:  # optional selfie runtime must never block V119
    print(f"[neyrobot-prod] celebrity selfie warning: {type(exc).__name__}: {exc}")
