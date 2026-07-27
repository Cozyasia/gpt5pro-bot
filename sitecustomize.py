# -*- coding: utf-8 -*-
"""Load independent Neyro-Bot runtime layers before main.py."""

try:
    from neyrobot_prod.bootstrap import install_early
    install_early()
except Exception as exc:
    print(f"[neyrobot-prod] production bootstrap warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.versioning import install_builder_hook as install_version_owner
    install_version_owner()
except Exception as exc:
    print(f"[neyrobot-prod] version owner warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.celebrity_selfie import install_async as install_celebrity_selfie
    install_celebrity_selfie()
except Exception as exc:
    print(f"[neyrobot-prod] celebrity selfie warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_commands_v206 import install_async as install_selfie_commands
    install_selfie_commands()
except Exception as exc:
    print(f"[neyrobot-prod] selfie commands warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod import selfie_v208_overlay as selfie_v208
    selfie_v208.MODE_LABELS.pop("движки", None)
    selfie_v208.MODE_LABELS.pop("баланс", None)
    selfie_v208.MODE_LABELS.pop("баланс/подписка", None)
    _v208_original_clear = selfie_v208._clear
    def _v208_clear_all(context, *, keep_photos=True):
        return _v208_original_clear(context, keep_photos=False)
    selfie_v208._clear = _v208_clear_all
    selfie_v208.install_async()
    from neyrobot_prod.selfie_v208_nav_guard import install_builder_hook as install_selfie_v208_nav_guard
    install_selfie_v208_nav_guard()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V208 warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_v209_canonical import install_async as install_selfie_v209
    install_selfie_v209()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V209 warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_v217_user_triref import install_async as install_selfie_v217
    install_selfie_v217()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V217 warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_v218_runtime_owner import install_async as install_selfie_v218
    install_selfie_v218()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V218 warning: {type(exc).__name__}: {exc}")

try:
    from neyrobot_prod.selfie_v219_triref_scene_owner import install_async as install_selfie_v219
    install_selfie_v219()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V219 warning: {type(exc).__name__}: {exc}")

try:
    # Visible/runtime owner for the canonical three-user/three-hero flow.
    from neyrobot_prod.selfie_v220_runtime_marker import install_async as install_selfie_v220
    install_selfie_v220()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V220 warning: {type(exc).__name__}: {exc}")

try:
    # Strict three-original-reference generator and uploaded-scene base semantics.
    from neyrobot_prod.selfie_v221_identity_scene_lock import install_async as install_selfie_v221
    install_selfie_v221()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V222 warning: {type(exc).__name__}: {exc}")

try:
    # Deterministic final owner: wraps V218/V219 patch workers so they cannot restore V220.
    from neyrobot_prod.selfie_v223_deterministic_owner import install_async as install_selfie_v223
    install_selfie_v223()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V223 warning: {type(exc).__name__}: {exc}")
