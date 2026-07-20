# -*- coding: utf-8 -*-
import unittest
from unittest.mock import AsyncMock, patch

import celebrity_selfie_v139 as v139
import celebrity_selfie_v139_compat as compat


class CelebritySelfieV139Tests(unittest.IsolatedAsyncioTestCase):
    def test_version_and_no_comet_provider_route(self):
        self.assertEqual(v139.VERSION, "v139-two-stage-celebrity-selfie-2026-07-20")
        source = open("celebrity_selfie_v139.py", encoding="utf-8").read()
        self.assertNotIn("COMET_API_KEY", source)
        self.assertNotIn("COMET_BASE_URL", source)
        self.assertIn('"nano_banana_comet": "disabled"', source)

    def test_scene_prompt_is_identity_free_and_two_person_specific(self):
        prompt = v139._scene_prompt("премьера", "4:5", 0)
        self.assertIn("Exactly TWO distinct anonymous foreground adults", prompt)
        self.assertIn("LEFT and RIGHT", prompt)
        self.assertIn("composition plate", prompt)
        self.assertNotIn("Роман Абрамович", prompt)
        self.assertNotIn("identity reference", prompt)

    def test_identity_prompts_modify_only_one_side(self):
        left = v139._identity_edit_prompt("left", "USER")
        right = v139._identity_edit_prompt("right", "PUBLIC PERSON")
        self.assertIn("ONLY the LEFT", left)
        self.assertIn("RIGHT foreground person pixel-stably", left)
        self.assertIn("ONLY the RIGHT", right)
        self.assertIn("LEFT foreground person pixel-stably", right)
        self.assertIn("Do not beautify", left)

    async def test_piapi_is_called_sequentially_with_one_target_index(self):
        task = AsyncMock(return_value=b"result")
        with patch.object(v139.pi_identity, "_piapi_task", task), \
             patch.object(v139, "_face_crop", return_value=b"face"), \
             patch.object(v139, "_jpeg", side_effect=lambda raw, **kwargs: raw):
            left = await v139._piapi_single_face(object(), b"scene", b"user", "left")
            right = await v139._piapi_single_face(object(), left, b"public", "right")
        self.assertEqual(right, b"result")
        first_inputs = task.await_args_list[0].args[2]
        second_inputs = task.await_args_list[1].args[2]
        self.assertEqual(first_inputs["swap_faces_index"], "0")
        self.assertEqual(first_inputs["target_faces_index"], "0")
        self.assertEqual(second_inputs["swap_faces_index"], "0")
        self.assertEqual(second_inputs["target_faces_index"], "1")

    async def test_pipeline_orders_scene_then_identity_then_repair(self):
        scene_candidate = {"label": "scene", "provider": "gemini", "score": 80, "output": b"scene"}
        final = {
            "label": "right-lock",
            "scene": "scene",
            "user_provider": "piapi",
            "celebrity_provider": "openai",
            "user_identity": 80,
            "celebrity_identity": 75,
            "identity_min": 75,
            "identity_weighted": 78,
            "identity_unknown": False,
            "structural": 90,
            "total": 80,
            "reason": "ok",
            "output": b"final",
        }
        repaired = {**final, "label": "repaired", "output": b"repaired"}
        with patch.object(v139.selfie.impl, "_best_reference", AsyncMock(return_value=b"public")), \
             patch.object(v139, "_make_scene_candidates", AsyncMock(return_value=[scene_candidate])) as scenes, \
             patch.object(v139, "_process_scene", AsyncMock(return_value=[final])) as identities, \
             patch.object(v139, "_repair_weak_side", AsyncMock(return_value=repaired)) as repair:
            output, debug = await v139._run_two_stage_generation(
                object(), b"user", [b"public"], "Person", "premiere"
            )
        self.assertEqual(output, b"repaired")
        scenes.assert_awaited_once()
        identities.assert_awaited_once()
        repair.assert_awaited_once()
        self.assertEqual(debug["architecture"], "scene_first+left_identity+right_identity+weak_side_repair")
        self.assertEqual(debug["selected"]["label"], "repaired")

    async def test_scene_failure_keeps_exact_diagnostic_class(self):
        with patch.object(v139.selfie.impl, "_best_reference", AsyncMock(return_value=b"public")), \
             patch.object(v139, "_make_scene_candidates", AsyncMock(return_value=[])):
            with self.assertRaises(v139.PipelineError) as raised:
                await v139._run_two_stage_generation(object(), b"user", [b"public"], "Person", "scene")
        self.assertEqual(raised.exception.category, "scene_generation")
        self.assertEqual(raised.exception.debug["failure_class"], "scene_generation")
        self.assertTrue(raised.exception.debug["run_id"])

    def test_error_taxonomy_is_actionable(self):
        self.assertEqual(v139._classify_error(RuntimeError("HTTP 429 rate limit")), "rate_limit")
        self.assertEqual(v139._classify_error(RuntimeError("HTTP 403 forbidden")), "auth_or_key")
        self.assertEqual(v139._classify_error(RuntimeError("provider returned no image")), "provider_error")
        self.assertIn("не вернули", v139._failure_message(v139.PipelineError("scene_generation", "x"), {}))

    def test_live_engine_is_v139_but_historical_v136_callable_is_restored(self):
        compat.install()
        self.assertIs(v139.selfie.engine._generate, v139._generate)
        self.assertIs(v139.selfie.engine._run_multi_reference_generation, v139._run_compat)
        self.assertIs(v139.selfie._run_v136_generation, v139.selfie.v134._run_face_first_generation)

    def test_diagnostic_commands_have_priority_over_old_routes(self):
        source = open("celebrity_selfie_v139.py", encoding="utf-8").read()
        self.assertIn('("diag_celebrity_flow", "diag_selfie_v139", "diag_brand")', source)
        self.assertLess(v139._GROUP, -2_000_000_000)
        self.assertIn("failure_class", source)
        self.assertIn("stages:", source)


if __name__ == "__main__":
    unittest.main()
