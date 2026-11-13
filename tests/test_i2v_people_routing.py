from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_helpers(*names: str, faces):
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    by_name = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module = ast.Module(
        body=[by_name[name] for name in names],
        type_ignores=[],
    )
    namespace = {
        "json": json,
        "log": logging.getLogger("i2v-routing-test"),
        "_get_cached_photo": lambda _user_id: b"portrait",
        "_detect_faces_for_choice": lambda _image: faces,
    }
    exec(compile(ast.fix_missing_locations(module), "main.py", "exec"), namespace)
    return namespace


class ImageToVideoPeopleRoutingTests(unittest.TestCase):
    def test_detected_face_routes_away_from_seedance_and_sora(self):
        helpers = _load_helpers(
            "_i2v_reference_has_detected_person",
            "_i2v_allowed_engines",
            faces=[{"x": 1, "y": 1, "w": 100, "h": 100}],
        )
        context = SimpleNamespace(user_data={})

        self.assertTrue(
            helpers["_i2v_reference_has_detected_person"](context, 42)
        )
        self.assertEqual(
            ("kling", "runway"),
            helpers["_i2v_allowed_engines"](context, 42),
        )

    def test_nonportrait_keeps_full_provider_selection(self):
        helpers = _load_helpers(
            "_i2v_reference_has_detected_person",
            "_i2v_allowed_engines",
            faces=[],
        )
        context = SimpleNamespace(user_data={})

        self.assertFalse(
            helpers["_i2v_reference_has_detected_person"](context, 42)
        )
        self.assertEqual(
            ("seedance", "kling", "runway", "sora"),
            helpers["_i2v_allowed_engines"](context, 42),
        )

    def test_seedance_real_person_rejection_is_recognized(self):
        helpers = _load_helpers(
            "_is_seedance_person_likeness_rejection",
            faces=[],
        )
        self.assertTrue(
            helpers["_is_seedance_person_likeness_rejection"](
                "The images or videos provided may contain likenesses of real people "
                "or other private information that cannot be processed."
            )
        )
        self.assertFalse(
            helpers["_is_seedance_person_likeness_rejection"]("temporary timeout")
        )


if __name__ == "__main__":
    unittest.main()
