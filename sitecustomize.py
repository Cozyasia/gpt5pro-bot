# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

v161 preserves the full v160 payment, routing, medical and general Celebrity
Selfie release, while restoring the proven PiAPI celebrity-lock/original-user
composite path for Roman Abramovich.
"""

try:
    from neyrobot_prod.hotfix_v161 import install_early as install_hotfix_v161
    install_hotfix_v161()
    from neyrobot_prod.topup_v159 import install_early as install_topup_v159
    install_topup_v159()
except Exception as exc:
    print(f"[neyrobot-v161] early bootstrap warning: {type(exc).__name__}: {exc}")

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
