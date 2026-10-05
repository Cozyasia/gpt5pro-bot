# -*- coding: utf-8 -*-
import ast
from pathlib import Path

def test_openai_selfie_experiment_is_isolated():
    src = Path("neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert 'PREFIX = "oaiselfie:"' in src
    assert "openai_selfie_" in src
    assert "dense68_engine_v265" not in src
    assert "selfie_v265_single_owner" not in src
    assert "cs201:" not in src

def test_openai_lane_uses_direct_image_edit():
    src = Path("neyrobot_prod/openai_selfie_exp_v1.py").read_text(encoding="utf-8")
    assert "https://api.openai.com/v1/images/edits" in src
    assert '"image[]"' in src
    assert "OPENAI_API_KEY" in src

def test_production_v265_not_modified_by_experiment():
    init = Path("neyrobot_prod/__init__.py").read_text(encoding="utf-8")
    assert 'PRODUCTION_SELFIE_RUNTIME = "v265"' in init
    assert "openai_selfie_exp_v1" in init
