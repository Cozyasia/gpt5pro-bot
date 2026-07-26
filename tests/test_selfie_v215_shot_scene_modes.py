from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "neyrobot_prod" / "selfie_v215_shot_scene_modes.py"


def _source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_v215_declares_two_shot_modes_and_three_scene_sources() -> None:
    source = _source()
    assert 'VERSION = "v215-selfie-shot-scene-production-2026-07-26"' in source
    assert 'SHOT_SELFIE = "selfie"' in source
    assert 'SHOT_THIRD_PERSON = "third_person"' in source
    assert 'SCENE_PRESET = "preset"' in source
    assert 'SCENE_DESCRIPTION = "description"' in source
    assert 'SCENE_IMAGE = "image"' in source
    assert "cs201:scene_mode:description" in source
    assert "cs201:scene_mode:image" in source


def test_v215_forbids_visible_phone_in_both_photo_modes() -> None:
    source = _source()
    assert "The phone/camera must remain outside the image and must not be visible" in source
    assert "This is not a selfie. Do not show a smartphone" in source
    assert "phone_visible_in_selfie=off" in source
    assert "phone_visible_in_third_person=off" in source


def test_v215_uses_uploaded_location_as_eighth_structural_reference() -> None:
    source = _source()
    assert "REFERENCE 8 is the user's uploaded location/room/venue" in source
    assert "SCENE STRUCTURE ONLY, NOT IDENTITY" in source
    assert "scene_image_references=0_or_1" in source
    assert "references_per_request=7_or_8" in source
    assert "Preserve its architecture, layout, furniture" in source


def test_v215_keeps_user_photos_and_reuse_controls_after_result() -> None:
    source = _source()
    assert "Повторить с текущей сценой" in source
    assert "Выбрать другого героя" in source
    assert "Сменить тип кадра" in source
    assert "Сменить фотографии пользователя" in source
    assert 'context.user_data["cs201_user_photos"] = list(photos[:2])' in source


def test_v215_adds_requested_heroes() -> None:
    source = _source()
    required = {
        "maria_aleksandrova": "Мария Александрова",
        "lyubov_aksenova": "Любовь Аксёнова",
        "johnny_depp": "Джонни Депп",
        "al_pacino": "Аль Пачино",
        "robert_de_niro": "Роберт Де Ниро",
        "alexander_petrov": "Александр Петров",
        "sergey_burunov": "Сергей Бурунов",
        "dmitry_nagiyev": "Дмитрий Нагиев",
        "eduard_bill": "Эдвард Билл",
        "mikhail_litvin": "Михаил Литвин",
        "garik_kharlamov": "Гарик Харламов",
    }
    for slug, name in required.items():
        assert f'"{slug}"' in source
        assert f'"name": "{name}"' in source


def test_v215_is_final_selfie_bootstrap_layer() -> None:
    policy = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    install_body = policy[policy.index("def install() -> None:"):]
    assert "_install_selfie_v214()" in install_body
    assert "_install_selfie_v215()" in install_body
    assert install_body.index("_install_selfie_v215()") > install_body.index("_install_selfie_v214()")


def test_v215_disables_historical_reclaimers() -> None:
    source = _source()
    assert "generator_v204.patch = lambda: True" in source
    assert "v208.patch = lambda: True" in source
    assert "v209.patch_runtime = lambda: True" in source
    assert "v210.patch_runtime = lambda: True" in source
    assert "runtime_v207.patch_runtime = lambda: True" in source
