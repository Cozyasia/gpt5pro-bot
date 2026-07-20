# -*- coding: utf-8 -*-
import unittest
from unittest.mock import AsyncMock, patch

import celebrity_selfie_v140 as v140


class CelebritySelfieV140Tests(unittest.IsolatedAsyncioTestCase):
    def test_version_and_no_comet_scene_route(self):
        self.assertEqual(v140.VERSION, "v140-scene-provider-rescue-2026-07-20")
        source = open("celebrity_selfie_v140.py", encoding="utf-8").read()
        self.assertNotIn("COMET_API_KEY", source)
        self.assertNotIn("api.cometapi.com", source)
        self.assertIn("https://api.openai.com/v1", source)

    def test_soft_scene_gate_ignores_only_one_face_false_negative(self):
        with patch.object(v140.v139, "_structural_problem", return_value="в сцене найдено только одно уверенное лицо"):
            self.assertEqual(v140._soft_scene_problem(b"image", "scene"), "")
        with patch.object(v140.v139, "_structural_problem", return_value="обнаружена техническая склейка или split-screen"):
            self.assertIn("split-screen", v140._soft_scene_problem(b"image", "scene"))

    async def test_scene_candidates_use_direct_provider_adapters(self):
        with patch.object(v140.v139.selfie.previous, "_gemini_key", return_value="key"), \
             patch.object(v140.v139.selfie.previous, "_gemini_models", return_value=["gemini-image"]), \
             patch.object(v140.v139.selfie, "_openai_key", return_value="key"), \
             patch.object(v140.v139.selfie, "_bfl_key", return_value=""), \
             patch.object(v140, "_gemini_scene_direct", AsyncMock(return_value=b"gemini")) as gemini, \
             patch.object(v140, "_openai_scene_direct", AsyncMock(return_value=b"openai")) as openai, \
             patch.object(v140, "_soft_scene_problem", return_value=""), \
             patch.object(v140.v139, "_structural_score", return_value=80.0):
            debug = v140.v139._new_debug("Person", "premiere", "4:5")
            candidates = await v140._make_scene_candidates(object(), "premiere", "4:5", debug)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(gemini.await_count, 2)
        openai.assert_awaited_once()
        self.assertTrue(all(item["score"] == 80.0 for item in candidates))

    async def test_rescue_scene_continues_into_sequential_identity_pipeline(self):
        rescue = {"label": "rescue", "provider": "openai", "score": 80.0, "output": b"scene"}
        final = {
            "label": "final",
            "scene": "rescue",
            "user_provider": "piapi",
            "celebrity_provider": "openai",
            "user_identity": 75.0,
            "celebrity_identity": 74.0,
            "identity_min": 74.0,
            "identity_weighted": 74.5,
            "identity_unknown": False,
            "structural": 80.0,
            "total": 76.0,
            "reason": "ok",
            "output": b"final",
        }
        with patch.object(v140.v139.selfie.impl, "_best_reference", AsyncMock(return_value=b"public")), \
             patch.object(v140, "_make_scene_candidates", AsyncMock(return_value=[])), \
             patch.object(v140, "_rescue_scene_candidate", AsyncMock(return_value=rescue)) as rescue_call, \
             patch.object(v140.v139, "_process_scene", AsyncMock(return_value=[final])) as process, \
             patch.object(v140.v139, "_repair_weak_side", AsyncMock(return_value=final)):
            output, debug = await v140._run_v140_generation(
                object(), b"user", [b"public"], "Person", "premiere"
            )
        self.assertEqual(output, b"final")
        rescue_call.assert_awaited_once()
        process.assert_awaited_once()
        self.assertEqual(debug["selected"]["label"], "final")
        self.assertEqual(debug["version"], v140.VERSION)

    def test_failure_card_includes_provider_cause(self):
        debug = {
            "failure_class": "scene_generation",
            "errors": [
                {
                    "stage": "scene_openai_1",
                    "provider": "openai:official-images",
                    "category": "auth_or_key",
                    "error": "HTTP 401 invalid key",
                }
            ],
        }
        message = v140._failure_message(v140.v139.PipelineError("scene_generation", "x"), debug)
        self.assertIn("Провайдеры не вернули", message)
        self.assertIn("scene_openai_1", message)
        self.assertIn("auth_or_key", message)

    def test_install_reasserts_live_engine_route(self):
        v140.install()
        self.assertIs(v140.v139._run_two_stage_generation, v140._run_v140_generation)
        self.assertIs(v140.v139.selfie.engine._run_multi_reference_generation, v140._run_compat)
        self.assertEqual(v140.v139.VERSION, v140.VERSION)


if __name__ == "__main__":
    unittest.main()
