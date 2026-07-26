from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V213 = ROOT / "neyrobot_prod" / "selfie_v213_user_identity_lock.py"


def test_v213_builds_seven_role_bound_references() -> None:
    source = V213.read_text(encoding="utf-8")
    assert 'VERSION = "v213-selfie-user-identity-lock-2026-07-26"' in source
    assert "USER ORIGINAL A" in source
    assert "USER FACE CROP A" in source
    assert "USER ORIGINAL B" in source
    assert "USER FACE CROP B" in source
    assert "REFERENCE 7" in source
    assert "references_per_request=7" in source


def test_v213_uses_face_crops_as_authoritative_identity_anchors() -> None:
    source = V213.read_text(encoding="utf-8")
    assert "_largest_face_box" in source
    assert "haarcascade_frontalface_default.xml" in source
    assert "_expanded_face_crop" in source
    assert "authoritative identity anchors" in source
    assert "Do not beautify, slim, age-shift" in source
    assert "Preserve realistic body size and proportions" in source


def test_v213_keeps_v211_delivery_and_replaces_only_generation() -> None:
    source = V213.read_text(encoding="utf-8")
    assert "from neyrobot_prod import selfie_v211_delivery as v211" in source
    assert "v208._comet_generate = comet_generate" in source
    assert "v211.VERSION = VERSION" in source


def test_v213_is_installed_after_v212() -> None:
    policy = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    install_body = policy[policy.index("def install() -> None:"):]
    assert "_install_selfie_admin_v212()" in install_body
    assert "_install_selfie_v213()" in install_body
    assert install_body.index("_install_selfie_v213()") > install_body.index("_install_selfie_admin_v212()")
