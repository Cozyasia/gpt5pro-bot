# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

v160 keeps the complete v159 payment, routing and medical release and adds a
production delivery rescue for Celebrity Selfie before main.py builds the
Telegram Application.
"""

try:
    from neyrobot_prod.hotfix_v160 import install_early as install_hotfix_v160
    install_hotfix_v160()
    from neyrobot_prod.topup_v159 import install_early as install_topup_v159
    install_topup_v159()
except Exception as exc:
    print(f"[neyrobot-v160] early bootstrap warning: {type(exc).__name__}: {exc}")

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
