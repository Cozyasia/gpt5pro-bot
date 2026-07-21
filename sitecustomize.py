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

# Keep v145 as the audited provider base, then apply v146 as the final local
# face-crop identity overlay. The explicit versioning bootstrap repeats v146 when
# Python does not automatically import repository-local sitecustomize.py.
try:
    from celebrity_selfie_v145 import install_early as install_celebrity_selfie_v145

    install_celebrity_selfie_v145()
except Exception as exc:  # keep the rest of the bot available for diagnostics
    print(f"[celebrity-selfie-v145] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from celebrity_selfie_v146 import install_early as install_celebrity_selfie_v146

    install_celebrity_selfie_v146()
except Exception as exc:  # keep the rest of the bot available for diagnostics
    print(f"[celebrity-selfie-v146] early bootstrap warning: {type(exc).__name__}: {exc}")
