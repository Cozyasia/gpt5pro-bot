from neyrobot_prod.star_selfie.models import CaptureMode
from neyrobot_prod.star_selfie.prompts.scene import build_scene_prompt


def test_true_selfie_forbids_visible_phone_and_third_person_view():
    prompt = build_scene_prompt("Hero", "restaurant", CaptureMode.TRUE_PHONE_SELFIE)
    assert "phone edge" in prompt
    assert "third-person camera viewpoint must be invisible" in prompt
    assert "exactly two adults" in prompt


def test_third_person_is_not_front_camera_selfie():
    prompt = build_scene_prompt("Hero", "premiere", CaptureMode.THIRD_PERSON)
    assert "THIRD-PERSON PHOTO" in prompt
    assert "Do not imitate a front-camera selfie perspective" in prompt
