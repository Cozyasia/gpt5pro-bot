# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

v162 preserves v161 rendering, payments, medicine and all product modes while
making one catalog/reference-backed Celebrity Selfie wizard authoritative.
"""

try:
    from neyrobot_prod.hotfix_v162 import install_early as install_hotfix_v162
    install_hotfix_v162()
    from neyrobot_prod.v161_reference_v2 import install as install_v161_reference_v2
    install_v161_reference_v2()
    from neyrobot_prod.topup_v159 import install_early as install_topup_v159
    install_topup_v159()
except Exception as exc:
    print(f"[neyrobot-v162] early bootstrap warning: {type(exc).__name__}: {exc}")

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
