# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

Only the current Celebrity Selfie release is activated here. Historical
celebrity-selfie overlays remain importable as implementation libraries, but are
not installed as competing runtime owners.
"""

# Patch compact, fully validated owner reference assets before any production
# bootstrap has a chance to install Celebrity Selfie v158.
try:
    from celebrity_selfie_reference_compat import install as install_reference_compat
    install_reference_compat()
except Exception as exc:
    print(f"[celebrity-reference-compat] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.bootstrap import install_early as install_production_early
    install_production_early()
except Exception as exc:
    print(f"[neyrobot-prod] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from celebrity_selfie_v158 import install_early as install_celebrity_selfie_v158
    install_celebrity_selfie_v158()
except Exception as exc:
    print(f"[celebrity-selfie-v158] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_early as install_version_contract_early
    install_version_contract_early()
except Exception as exc:
    print(f"[neyrobot-version] early bootstrap warning: {type(exc).__name__}: {exc}")
