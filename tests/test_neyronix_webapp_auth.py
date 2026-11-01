import ast
import hashlib
import hmac
import json
import time
import urllib.parse
from pathlib import Path

import pytest


def _validator(token: str):
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_validate_telegram_webapp_init_data"
    )
    namespace = {
        "BOT_TOKEN": token,
        "hashlib": hashlib,
        "hmac": hmac,
        "json": json,
        "time": time,
        "urllib": urllib,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["_validate_telegram_webapp_init_data"]


def _signed_init_data(token: str, *, user_id: int = 42, auth_date: int | None = None) -> str:
    data = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AA-test-query",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(data)


def test_valid_init_data_binds_server_side_user():
    token = "123456:test-token"
    result = _validator(token)(_signed_init_data(token, user_id=987654))
    assert result["user_id"] == 987654
    assert result["user_obj"]["first_name"] == "Test"


def test_tampered_user_id_is_rejected():
    token = "123456:test-token"
    payload = _signed_init_data(token, user_id=42).replace("%3A42", "%3A43")
    with pytest.raises(ValueError, match="signature is invalid"):
        _validator(token)(payload)


def test_expired_init_data_is_rejected():
    token = "123456:test-token"
    payload = _signed_init_data(token, auth_date=int(time.time()) - 86_401)
    with pytest.raises(ValueError, match="expired"):
        _validator(token)(payload, max_age_s=86_400)

