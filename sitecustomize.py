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

# Keep the audited historical overlays available, then apply v148 last. v148
# removes Gemini responseFormat/aspect fields and uses validated source-layer
# placement geometry instead of a fallible post-JPEG face detector.
try:
    from celebrity_selfie_v145 import install_early as install_celebrity_selfie_v145

    install_celebrity_selfie_v145()
except Exception as exc:
    print(f"[celebrity-selfie-v145] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from celebrity_selfie_v146 import install_early as install_celebrity_selfie_v146

    install_celebrity_selfie_v146()
except Exception as exc:
    print(f"[celebrity-selfie-v146] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from celebrity_selfie_v147 import install_early as install_celebrity_selfie_v147

    install_celebrity_selfie_v147()
except Exception as exc:
    print(f"[celebrity-selfie-v147] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from celebrity_selfie_v148 import install_early as install_celebrity_selfie_v148

    install_celebrity_selfie_v148()
except Exception as exc:
    print(f"[celebrity-selfie-v148] early bootstrap warning: {type(exc).__name__}: {exc}")
