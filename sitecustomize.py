# -*- coding: utf-8 -*-
"""Early Neyro-Bot production bootstrap.

v159 is the single release owner. It installs the priority Celebrity Selfie
wizard, canonical credit catalog/YooKassa routing and medical runtime integrity
before main.py builds the Telegram Application.
"""

try:
    from neyrobot_prod.hotfix_v159 import install_early as install_hotfix_v159
    install_hotfix_v159()
except Exception as exc:
    print(f"[neyrobot-v159] early bootstrap warning: {type(exc).__name__}: {exc}")

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
