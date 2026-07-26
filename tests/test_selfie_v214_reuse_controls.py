from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V214 = ROOT / "neyrobot_prod" / "selfie_v214_reuse_controls.py"


def test_v214_exposes_all_post_result_actions() -> None:
    source = V214.read_text(encoding="utf-8")
    assert 'VERSION = "v214-selfie-reuse-controls-2026-07-26"' in source
    assert "🎬 Другая сцена" in source
    assert 'callback_data=f"cs201:character:{slug}"' in source
    assert "⭐ Выбрать другого героя" in source
    assert 'callback_data="cs201:characters"' in source
    assert "📸 Сменить фотографии пользователя" in source
    assert 'callback_data="cs201:photo"' in source


def test_v214_preserves_user_photos_and_selected_hero() -> None:
    source = V214.read_text(encoding="utf-8")
    assert "_preserve_generation_state" in source
    assert 'context.user_data["cs201_character"] = slug' in source
    assert 'context.user_data["cs201_user_photos"] = list(photos[:2])' in source
    assert 'context.user_data["cs201_user_photo_ready"] = len(photos) == 2' in source
    assert "keep_photos=False" not in source


def test_v214_keeps_identity_and_delivery_layers() -> None:
    source = V214.read_text(encoding="utf-8")
    assert "from neyrobot_prod import selfie_v211_delivery as v211" in source
    assert "from neyrobot_prod import selfie_v213_user_identity_lock as v213" in source
    assert "output = await v208._comet_generate" in source
    assert "delivered = await v211._deliver" in source
    assert "7 референсов с усилением личности пользователя" in source


def test_v214_is_installed_last() -> None:
    policy = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    install_body = policy[policy.index("def install() -> None:"):]
    assert "_install_selfie_v213()" in install_body
    assert "_install_selfie_v214()" in install_body
    assert install_body.index("_install_selfie_v214()") > install_body.index("_install_selfie_v213()")
