# -*- coding: utf-8 -*-
import inspect
import unittest

import celebrity_selfie_v129 as v129


class InspectCelebrityEngineTemp(unittest.TestCase):
    def test_dump_engine_surface(self):
        engine = v129.engine
        core = v129.core
        names = []
        for name in sorted(set(dir(engine)) | set(dir(core))):
            low = name.lower()
            if any(token in low for token in ("generat", "refine", "swap", "scene", "result", "reference", "session", "photo", "image", "quality", "similar")):
                obj = getattr(engine, name, None)
                owner = "engine"
                if obj is None:
                    obj = getattr(core, name, None)
                    owner = "core"
                if callable(obj):
                    try:
                        sig = str(inspect.signature(obj))
                    except Exception:
                        sig = "(?)"
                    names.append(f"{owner}.{name}{sig}")
                else:
                    names.append(f"{owner}.{name}={type(obj).__name__}:{obj!r}"[:500])
        self.fail("ENGINE_SURFACE\n" + "\n".join(names))


if __name__ == "__main__":
    unittest.main()
