# -*- coding: utf-8 -*-
"""Regression test for the OpenAI/httpx startup compatibility used by Render."""
from __future__ import annotations

import unittest

import httpx
from openai import AsyncOpenAI, OpenAI


class OpenAIHttpxCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_sync_client_can_be_constructed(self) -> None:
        client = OpenAI(api_key="sk-test", base_url="https://example.invalid/v1")
        try:
            self.assertIsNotNone(client)
            self.assertTrue(httpx.__version__.startswith("0.27."))
        finally:
            client.close()

    async def test_async_client_can_be_constructed(self) -> None:
        client = AsyncOpenAI(api_key="sk-test", base_url="https://example.invalid/v1")
        try:
            self.assertIsNotNone(client)
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
