# -*- coding: utf-8 -*-
import inspect
from pathlib import Path
import unittest

import celebrity_selfie_v129 as v129


class InspectCelebrityEngineTemp(unittest.TestCase):
    def test_dump_engine_surface(self):
        engine = v129.engine
        core = v129.core
        names = []
        for owner_name, owner in (("engine", engine), ("core", core)):
            for name in sorted(set(dir(owner))):
                low = name.lower()
                if not any(token in low for token in (
                    "generat", "refine", "swap", "scene", "result", "reference",
                    "session", "photo", "image", "quality", "similar", "callback",
                )):
                    continue
                obj = getattr(owner, name, None)
                if callable(obj):
                    try:
                        sig = str(inspect.signature(obj))
                    except Exception:
                        sig = "(?)"
                    names.append(f"{owner_name}.{name}{sig}")
                else:
                    names.append(f"{owner_name}.{name}={type(obj).__name__}:{obj!r}"[:1000])
        Path("engine_surface.txt").write_text("\n".join(names), encoding="utf-8")
        self.fail("engine surface written to artifact")


if __name__ == "__main__":
    unittest.main()
