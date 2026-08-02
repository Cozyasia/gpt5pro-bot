from neyrobot_prod.star_selfie.models import CaptureMode
from neyrobot_prod.star_selfie.prompts.scene import build_scene_prompt


def test_true_selfie_forbids_visible_phone_and_locks_identities():
    prompt = build_scene_prompt("Hero", "restaurant", CaptureMode.TRUE_PHONE_SELFIE)
    assert "front-camera selfie" in prompt
    assert "do not show the phone" in prompt
    assert "PERSON A is the user" in prompt
    assert "PERSON B is the selected celebrity" in prompt
    assert "must remain on image-left" in prompt
    assert "must remain on image-right" in prompt


def test_third_person_preserves_mature_celebrity_and_terminal_face_swap_target():
    prompt = build_scene_prompt("Hero", "premiere", CaptureMode.THIRD_PERSON)
    assert "third-person joint photograph" in prompt
    assert "not a younger version" in prompt
    assert "later exact external face replacement" in prompt
    assert "PERSON B must be immediately recognizable" in prompt
