# -*- coding: utf-8 -*-
import contextlib
import dis
import inspect
from io import StringIO
from pathlib import Path
import unittest

import celebrity_selfie_v129 as v129


class InspectCelebrityEngineTemp(unittest.TestCase):
    def test_dump_engine_surface(self):
        engine = v129.engine
        core = v129.core
        lines = []
        for owner_name, owner in (("engine", engine), ("core", core)):
            for name in sorted(set(dir(owner))):
                low = name.lower()
                if not any(token in low for token in (
                    "generat", "refine", "swap", "scene", "result", "reference",
                    "session", "photo", "image", "quality", "similar", "callback",
                    "catalog", "library", "model", "comet", "gemini",
                )):
                    continue
                obj = getattr(owner, name, None)
                if callable(obj):
                    try:
                        sig = str(inspect.signature(obj))
                    except Exception:
                        sig = "(?)"
                    lines.append(f"{owner_name}.{name}{sig}")
                else:
                    lines.append(f"{owner_name}.{name}={type(obj).__name__}:{obj!r}"[:2000])

        for name in (
            "_generate",
            "_run_multi_reference_generation",
            "_on_callback",
            "_after_user_photo",
            "_reference_paths",
            "_result_kb",
        ):
            func = getattr(engine, name)
            lines.append(f"\n===== DIS {name} =====")
            buf = StringIO()
            with contextlib.redirect_stdout(buf):
                dis.dis(func)
            lines.append(buf.getvalue())
            lines.append(f"CONSTS={func.__code__.co_consts!r}")
            lines.append(f"NAMES={func.__code__.co_names!r}")
            lines.append(f"VARS={func.__code__.co_varnames!r}")

        Path("engine_surface.txt").write_text("\n".join(lines), encoding="utf-8")
        self.fail("engine surface written to artifact")


if __name__ == "__main__":
    unittest.main()
