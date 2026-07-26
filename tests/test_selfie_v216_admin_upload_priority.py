from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "neyrobot_prod" / "selfie_v216_admin_upload_priority.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_v216_recognizes_every_historical_admin_upload_state() -> None:
    source = _source()
    assert 'VERSION = "v216-selfie-admin-upload-priority-2026-07-26"' in source
    for key in (
        "cs212_admin_upload",
        "ss205_admin_upload",
        "cs202_admin_upload",
        "cs201_admin_upload",
    ):
        assert f'"{key}"' in source


def test_v216_routes_admin_media_before_public_v215_media() -> None:
    source = _source()
    assert "await admin_v212.media(update, context)" in source
    assert "await storage_v205.media_entry(update, context)" in source
    assert "await admin_v202.media(update, context)" in source
    assert "await base.media_entry(update, context)" in source
    assert "await v215.public_media(update, context)" in source
    assert source.index("await admin_v212.media(update, context)") < source.index(
        "await v215.public_media(update, context)"
    )


def test_v216_clears_public_wait_flags_during_admin_upload() -> None:
    source = _source()
    assert 'context.user_data.pop("cs215_await_scene_image", None)' in source
    assert 'context.user_data.pop("awaiting_ai_selfie_photo", None)' in source
    assert 'context.user_data.pop("cs215_wait_scene_text", None)' in source


def test_v216_makes_v212_the_canonical_admin_command() -> None:
    source = _source()
    assert "await admin_v212.command(update, context)" in source
    assert "v208._admin_command = canonical_admin_command" in source
    assert "v208._public_media = media_router" in source
    assert "base.media_entry = media_router" in source


def test_v216_is_installed_after_v215() -> None:
    policy = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    install_body = policy[policy.index("def install() -> None:"):]
    assert "_install_selfie_v215()" in install_body
    assert "_install_selfie_v216()" in install_body
    assert install_body.index("_install_selfie_v216()") > install_body.index(
        "_install_selfie_v215()"
    )
