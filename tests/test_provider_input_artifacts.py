import ast
import contextlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def _load_provider_input_helpers(directory: str):
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names = {
        "_provider_input_extension",
        "_provider_input_artifact_path",
        "_prune_provider_input_artifacts",
        "_provider_input_url_from_bytes",
        "_provider_input_content_type",
        "_read_provider_input_artifact",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    namespace = {
        "os": __import__("os"),
        "re": __import__("re"),
        "time": __import__("time"),
        "contextlib": contextlib,
        "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="a" * 32)),
        "PUBLIC_URL": "https://gpt5pro-bot.onrender.com",
        "PROVIDER_INPUT_DIR": directory,
        "PROVIDER_INPUT_TTL_S": 3600,
        "PROVIDER_INPUT_MAX_BYTES": 1024 * 1024,
        "BOT_TOKEN": "must-never-appear-in-provider-url",
        "log": SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"),
        namespace,
    )
    return namespace


class ProviderInputArtifactTests(unittest.TestCase):
    def test_image_artifact_uses_opaque_render_url_without_bot_token(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _load_provider_input_helpers(directory)
            url = env["_provider_input_url_from_bytes"](b"portrait-bytes", "performer.jpg")

            self.assertEqual(
                "https://gpt5pro-bot.onrender.com/provider-input/" + "a" * 32 + ".jpg",
                url,
            )
            self.assertNotIn("must-never-appear", url)
            artifact = Path(directory) / ("a" * 32 + ".jpg")
            self.assertEqual(b"portrait-bytes", artifact.read_bytes())

            content_type, body = env["_read_provider_input_artifact"](artifact.name)
            self.assertEqual("image/jpeg", content_type)
            self.assertEqual(b"portrait-bytes", body)

    def test_expired_artifact_is_not_served(self):
        with tempfile.TemporaryDirectory() as directory:
            env = _load_provider_input_helpers(directory)
            env["_provider_input_url_from_bytes"](b"song", "vocal.mp3")
            artifact = Path(directory) / ("a" * 32 + ".mp3")
            old = __import__("time").time() - 7200
            __import__("os").utime(artifact, (old, old))

            self.assertIsNone(env["_read_provider_input_artifact"](artifact.name))
            self.assertFalse(artifact.exists())

    def test_vocal_lipsync_and_render_route_use_only_provider_artifacts(self):
        source = MAIN.read_text(encoding="utf-8")
        lipsync_start = source.index("async def _apply_kling_lipsync_to_scene_file")
        lipsync_end = source.index("\nasync def ", lipsync_start + 30)
        lipsync = source[lipsync_start:lipsync_end]
        self.assertIn("_provider_input_url_from_file", lipsync)
        self.assertIn("_provider_input_url_from_bytes", lipsync)
        self.assertNotIn("_upload_file_to_telegram_file_url", lipsync)
        self.assertNotIn("_upload_bytes_to_telegram_file_url", lipsync)
        self.assertIn('r"/provider-input/([0-9a-f]{32}', source)


if __name__ == "__main__":
    unittest.main()
