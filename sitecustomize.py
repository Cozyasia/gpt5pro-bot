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
except Exception as exc:  # optional selfie runtime must never block production
    print(f"[neyrobot-prod] celebrity selfie warning: {type(exc).__name__}: {exc}")

try:
    # Must be installed before main.py calls ApplicationBuilder.build().
    # V206 also re-binds the routes to an existing Application as a fallback.
    from neyrobot_prod.selfie_commands_v206 import install_async as install_selfie_commands

    install_selfie_commands()
except Exception as exc:  # service commands must never block bot startup
    print(f"[neyrobot-prod] selfie commands warning: {type(exc).__name__}: {exc}")

try:
    # Final V208 owner: two user references, country catalogue and safe mode exits.
    from neyrobot_prod.selfie_v208_overlay import install_async as install_selfie_v208

    install_selfie_v208()
except Exception as exc:  # V208 must remain fail-safe and diagnosable
    print(f"[neyrobot-prod] selfie V208 warning: {type(exc).__name__}: {exc}")
