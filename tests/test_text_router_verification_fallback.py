import asyncio
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    sys.modules["httpx"] = SimpleNamespace(AsyncClient=None, Timeout=lambda **kwargs: kwargs)
import text_router_v114 as router


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text
        self.headers = {"x-request-id": "request-1"}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    calls = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def post(self, _url, headers, json):
        self.__class__.calls.append(json["model"])
        if json["model"].startswith("gpt-5"):
            return FakeResponse(404, text="Your organization must be verified to use the model")
        return FakeResponse(200, {
            "output_text": "fallback-ok",
            "usage": {"input_tokens": 10, "output_tokens": 2},
        })


class VerificationFallbackTests(unittest.TestCase):
    def setUp(self):
        FakeClient.calls.clear()
        router._MODEL_DENIAL_CACHE.clear()

    def _call(self):
        module = SimpleNamespace(OPENAI_API_KEY="test-key", log=None)
        return asyncio.run(router._responses_call(
            module, "answer", [{"role": "user", "content": "hello"}],
            "gpt-5-mini", "low", 100,
        ))

    def test_verification_denial_falls_back_once_and_is_cached(self):
        async def models(_mod, _primary):
            return ["gpt-5-mini", "gpt-5", "gpt-4.1-mini"]

        with patch.object(router, "_resolve_models", models), \
             patch.object(router.httpx, "AsyncClient", FakeClient), \
             patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            self.assertEqual("fallback-ok", self._call())
            self.assertEqual(["gpt-5-mini", "gpt-4.1-mini"], FakeClient.calls)
            FakeClient.calls.clear()
            self.assertEqual("fallback-ok", self._call())
            self.assertEqual(["gpt-4.1-mini"], FakeClient.calls)


if __name__ == "__main__":
    unittest.main()
