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
    # V208 implements the country catalogue and isolated public selfie flow.
    from neyrobot_prod import selfie_v208_overlay as selfie_v208

    # Engines and billing retain their existing dedicated routers; V208 owns only
    # the four main mode buttons that could previously be mistaken for a scene.
    selfie_v208.MODE_LABELS.pop("движки", None)
    selfie_v208.MODE_LABELS.pop("баланс", None)
    selfie_v208.MODE_LABELS.pop("баланс/подписка", None)

    # User selfies are temporary request data. Always release them when a flow is
    # completed, restarted or exited so stale scenes cannot rerun and RAM does not grow.
    _v208_original_clear = selfie_v208._clear

    def _v208_clear_all(context, *, keep_photos=True):
        return _v208_original_clear(context, keep_photos=False)

    selfie_v208._clear = _v208_clear_all
    selfie_v208.install_async()

    from neyrobot_prod.selfie_v208_nav_guard import install_builder_hook as install_selfie_v208_nav_guard

    install_selfie_v208_nav_guard()
except Exception as exc:  # V208 must remain fail-safe and diagnosable
    print(f"[neyrobot-prod] selfie V208 warning: {type(exc).__name__}: {exc}")

try:
    # V209 binds V208 handlers directly at higher priority and prevents the later
    # V207 bootstrap from restoring the obsolete one-selfie/flat-list workflow.
    from neyrobot_prod.selfie_v209_canonical import install_async as install_selfie_v209

    install_selfie_v209()
except Exception as exc:  # canonical selfie ownership must stay diagnosable
    print(f"[neyrobot-prod] selfie V209 warning: {type(exc).__name__}: {exc}")

try:
    # V217 implements three user references and equal identity priority.
    from neyrobot_prod.selfie_v217_user_triref import install_async as install_selfie_v217

    install_selfie_v217()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V217 warning: {type(exc).__name__}: {exc}")

try:
    # V218 owns the final PTB handlers themselves. This is required because handlers
    # created by older layers retain their original callback objects after monkeypatching.
    from neyrobot_prod.selfie_v218_runtime_owner import install_async as install_selfie_v218

    install_selfie_v218()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V218 warning: {type(exc).__name__}: {exc}")

try:
    # V219 is the final canonical owner: three user photos, three hero references,
    # and uploaded-scene routing before the generic photo-processing pipeline.
    from neyrobot_prod.selfie_v219_triref_scene_owner import install_async as install_selfie_v219

    install_selfie_v219()
except Exception as exc:
    print(f"[neyrobot-prod] selfie V219 warning: {type(exc).__name__}: {exc}")
