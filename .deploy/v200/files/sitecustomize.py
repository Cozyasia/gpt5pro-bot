# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

Celebrity Selfie is now a normal, directly registered feature in ``main.py``.
No historical selfie overlays, builder monkey patches, or runtime stampers are
loaded here.
"""

try:
    from neyrobot_prod.bootstrap import install_early as install_production_early
    install_production_early()
except Exception as exc:
    print(f"[neyrobot-prod] early bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_early as install_version_contract_early
    install_version_contract_early()
except Exception as exc:
    print(f"[neyrobot-version] early bootstrap warning: {type(exc).__name__}: {exc}")
