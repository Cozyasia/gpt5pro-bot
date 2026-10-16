"""Offline contracts for the user-supplied vocal-track Telegram path."""
import ast
import asyncio
import contextlib
import hashlib
from pathlib import Path
import unittest
import uuid


SOURCE = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")


class VocalClipCustomAudioFlowTests(unittest.TestCase):
    def test_menu_exposes_a_custom_audio_choice(self):
        self.assertIn('callback_data=f"{base}:vocalclip_audio"', SOURCE)

    def test_audio_is_consumed_before_stt_and_saved_as_the_vocal_source(self):
        marker = 'if context.user_data.get("awaiting_vocal_clip_audio"):'
        self.assertIn(marker, SOURCE)
        self.assertLess(SOURCE.index(marker), SOURCE.index("    # STT"))
        self.assertIn('_save_vocal_artifact, update.effective_user.id, token, "audio", source_audio', SOURCE)
        self.assertIn('"vocal_audio_is_custom"', SOURCE)

    def test_transient_state_clears_the_custom_audio_wait(self):
        self.assertIn('"awaiting_vocal_clip_audio",', SOURCE)

    def test_staging_preserves_selected_custom_audio_for_approval(self):
        module = ast.parse(SOURCE)
        function = next(
            node for node in module.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_stage_music_video_draft"
        )

        class ContextTypes:
            DEFAULT_TYPE = object

        class Plan:
            fingerprint = "test-plan"

        class Message:
            async def reply_text(self, *_args, **_kwargs):
                return None

        class User:
            id = 101

        class Update:
            effective_user = User()
            effective_message = Message()
            effective_chat = type("Chat", (), {"id": 202})()

        class Context:
            user_data = {
                "vocal_audio_is_custom": True,
                "vocal_source_token": "uploaded-source",
            }

        async def compile_plan(*_args, **_kwargs):
            return Plan()

        namespace = {
            "ContextTypes": ContextTypes,
            "Update": Update,
            "PHOTO_CLIP_MAX_DURATION_S": 90,
            "_photo_clip_target_duration": lambda _text: 10,
            "_music_video_aspect": lambda _text: "9:16",
            "_music_video_join_briefs": lambda music, video: f"{music}\\n{video}",
            "_compile_music_video_scene_plan": compile_plan,
            "_get_cached_photo": lambda _user_id: b"portrait",
            "_clip_wants_vocals": lambda _text: True,
            "_load_vocal_artifact": lambda *_args: b"source-audio",
            "_send_music_video_review": compile_plan,
            "hashlib": hashlib,
            "contextlib": contextlib,
            "uuid": uuid,
            "log": type("Log", (), {"exception": lambda *_args, **_kwargs: None})(),
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), "<stage>", "exec"), namespace)

        context = Context()
        staged = asyncio.run(
            namespace["_stage_music_video_draft"](
                Update(), context, music_brief="русский мужской вокал", video_brief="певец в кадре"
            )
        )

        self.assertTrue(staged)
        self.assertEqual(context.user_data["vocal_source_token"], "uploaded-source")
        self.assertIn("пользовательская исходная аудиодорожка", context.user_data["music_video_draft"]["source_note"])


if __name__ == "__main__":
    unittest.main()
