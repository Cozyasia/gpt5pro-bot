# -*- coding: utf-8 -*-
"""Production bootstrap for Neyro-Bot.

Only shared production hardening and the canonical /version command are
installed here. The former Celebrity Selfie feature has been removed entirely;
this bootstrap contains no menu hooks, callbacks, handlers, providers, guards,
or compatibility aliases for that feature.
"""
from __future__ import annotations

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}", flush=True)

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}", flush=True)
