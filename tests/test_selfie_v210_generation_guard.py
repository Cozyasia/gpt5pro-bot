from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v210_is_installed_after_v209_from_guaranteed_bootstrap() -> None:
    source = (ROOT / "model_policy_v115.py").read_text(encoding="utf-8")
    install_body = source[source.index("def install() -> None:"):]
    assert "selfie_v210_generation_guard" in source
    assert "_install_selfie_v209()" in install_body
    assert "_install_selfie_v210()" in install_body
    assert install_body.index("_install_selfie_v210()") > install_body.index("_install_selfie_v209()")


def test_v210_accepts_legacy_and_v208_generator_signatures() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v210_generation_guard.py").read_text(encoding="utf-8")
    assert "if len(args) == 4" in source
    assert "elif len(args) == 3" in source
    assert "base._generate = generate" in source
    assert "generator_v204.generate = generate" in source


def test_v210_stops_generation_reclaimers_and_duplicate_taps() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v210_generation_guard.py").read_text(encoding="utf-8")
    assert "generator_v204.patch = lambda: True" in source
    assert "v208.patch = lambda: True" in source
    assert "v209.patch_runtime = lambda: True" in source
    assert "runtime_v207.patch_runtime = lambda: True" in source
    assert "AI-селфи уже создаётся" in source
    assert "_BUSY_TTL_SECONDS" in source


def test_v210_publishes_component_version() -> None:
    source = (ROOT / "neyrobot_prod" / "selfie_v210_generation_guard.py").read_text(encoding="utf-8")
    assert 'VERSION = "v210-selfie-generation-guard-2026-07-26"' in source
    assert "runtime.CELEBRITY_SELFIE_VERSION = VERSION" in source
    assert "runtime.SELFIE_STORAGE_VERSION = VERSION" in source
    assert "runtime.SELFIE_COMMANDS_VERSION = VERSION" in source
