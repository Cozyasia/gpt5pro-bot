import ast
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import tempfile
import time
import unittest
import uuid


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def load_helpers(root):
    names = {
        "_vocal_job_path", "_save_vocal_job_manifest", "_load_vocal_job_manifest",
        "_save_vocal_job_file", "_save_vocal_job_file_from_path",
        "_load_vocal_job_file_path", "_extract_vocal_intervals",
        "_verified_lipsync_window",
    }
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    env = {
        "contextlib": contextlib, "json": json, "os": os, "re": re,
        "shutil": shutil, "time": time, "uuid": uuid,
        "VOCAL_CLIP_ARTIFACT_DIR": root,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(MAIN), "exec"), env)
    return env


class MusicVideoCheckpointTests(unittest.TestCase):
    def test_manifest_and_scene_survive_and_preserve_provider_ids(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_helpers(root)
            token = "0123456789ab"
            manifest = {
                "schema": 1,
                "scene_plan_fingerprint": "immutable-plan-sha",
                "world_state": {"wardrobe": "red jacket"},
                "provider_tasks": {"suno_task_id": "suno-1", "scene_1_task_id": "kling-1"},
                "completed_stages": ["song", "scene_1_base"],
            }
            env["_save_vocal_job_manifest"](42, token, manifest)
            scene_path = env["_save_vocal_job_file"](42, token, "scene_01_base", "mp4", b"mp4-checkpoint")

            self.assertEqual(manifest, env["_load_vocal_job_manifest"](42, token))
            self.assertEqual(scene_path, env["_load_vocal_job_file_path"](42, token, "scene_01_base", "mp4"))
            self.assertEqual(b"mp4-checkpoint", Path(scene_path).read_bytes())

    def test_invalid_reference_cannot_escape_artifact_directory(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_helpers(root)
            with self.assertRaises(ValueError):
                env["_vocal_job_path"](42, "../../etc/pass", "job", "json")
            with self.assertRaises(ValueError):
                env["_vocal_job_path"](42, "0123456789ab", "../scene", "mp4")

    def test_expired_checkpoint_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as root:
            env = load_helpers(root)
            token = "0123456789ab"
            env["_save_vocal_job_manifest"](42, token, {"schema": 1})
            path = env["_vocal_job_path"](42, token, "job", "json")
            old = time.time() - 8 * 86400
            os.utime(path, (old, old))
            self.assertIsNone(env["_load_vocal_job_manifest"](42, token))

    def test_lipsync_uses_only_verified_vocal_overlap(self):
        env = load_helpers("/tmp/unused")
        timing = {"data": [{"word": "hello", "startTime": "2500", "endTime": "6100"}]}
        intervals = env["_extract_vocal_intervals"](timing, 10)
        contract = SimpleNamespace(lip_sync_start_s=0.0, lip_sync_end_s=6.0)
        self.assertEqual([(2.5, 6.1)], intervals)
        self.assertEqual((2.5, 6.0), env["_verified_lipsync_window"](contract, intervals))

    def test_instrumental_timing_does_not_trigger_lipsync(self):
        env = load_helpers("/tmp/unused")
        intervals = env["_extract_vocal_intervals"]({"data": [{"start": 0, "end": 10}]}, 10)
        contract = SimpleNamespace(lip_sync_start_s=0.0, lip_sync_end_s=6.0)
        self.assertEqual([], intervals)
        self.assertIsNone(env["_verified_lipsync_window"](contract, intervals))


if __name__ == "__main__":
    unittest.main()
