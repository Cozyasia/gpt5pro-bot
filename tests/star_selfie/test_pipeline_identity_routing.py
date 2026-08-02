from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neyrobot_prod.star_selfie.models import CaptureMode, Character, GenerationRequest
from neyrobot_prod.star_selfie.pipeline import StarSelfiePipeline
from neyrobot_prod.star_selfie.storage import StarSelfieStorage


JPEG = b"\xff\xd8\xff" + b"x" * 25000
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 25000


class _SceneProvider:
    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return PNG


class _FaceSwapProvider:
    def __init__(self):
        self.calls = []

    async def swap_face(self, *, source_face, target_scene, target_face_index):
        self.calls.append(
            {
                "source_face": source_face,
                "target_scene": target_scene,
                "target_face_index": target_face_index,
            }
        )
        return PNG + b"user-face-transfer"


class PipelineIdentityRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_v232_scene_then_terminal_user_only_face_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_face = root / "user-face.jpg"
            user_body = root / "user-body.jpg"
            user_face.write_bytes(JPEG + b"face")
            user_body.write_bytes(JPEG + b"body")

            refs = []
            for index in range(3):
                path = root / f"hero-{index}.jpg"
                path.write_bytes(JPEG + bytes([index]))
                refs.append(path)

            scene_provider = _SceneProvider()
            face_provider = _FaceSwapProvider()
            pipeline = StarSelfiePipeline(
                scene_provider,
                face_provider,
                StarSelfieStorage(root / "out"),
                max_attempts=2,
                face_swap_attempts=2,
            )
            request = GenerationRequest(
                user_id=7,
                user_face_path=user_face,
                user_body_path=user_body,
                character=Character(
                    slug="basta",
                    title="Баста",
                    active=True,
                    reference_paths=refs,
                ),
                scene="restaurant",
                capture_mode=CaptureMode.THIRD_PERSON,
            )

            result = await pipeline.run(request)

            self.assertEqual(len(scene_provider.calls), 1)
            scene_call = scene_provider.calls[0]
            self.assertEqual(
                scene_call["character_references"],
                [path.read_bytes() for path in refs],
            )
            self.assertEqual(scene_call["user_face_reference"], user_face.read_bytes())
            self.assertEqual(scene_call["user_body_reference"], user_body.read_bytes())

            self.assertEqual(len(face_provider.calls), 1)
            self.assertEqual(face_provider.calls[0]["source_face"], user_face.read_bytes())
            self.assertEqual(face_provider.calls[0]["target_face_index"], 0)
            self.assertTrue(result.metadata["celebrity_face_swap_disabled"])
            self.assertFalse(result.metadata["post_swap_gemini_pass"])
            self.assertEqual(
                result.metadata["architecture"],
                "v232_scene_plus_terminal_user_only_face_swap",
            )


if __name__ == "__main__":
    unittest.main()
