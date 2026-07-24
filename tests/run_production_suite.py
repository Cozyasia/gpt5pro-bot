# -*- coding: utf-8 -*-
"""Run the current production contract.

Historical Celebrity Selfie modules remain in the repository only as source
history. They are not imported by the clean v200 runtime and their mutually
exclusive release tests must not participate in production CI.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = ROOT / "tests"

RETIRED_PATTERNS = (
    re.compile(r"^test_celebrity_selfie_(?!clean\.py$)"),
    re.compile(r"^test_hotfix_v(?:159|160|161|162)\.py$"),
    re.compile(r"^test_ui_selfie_v138\.py$"),
    re.compile(r"^test_main_ai_selfie_callback_contract\.py$"),
    re.compile(r"^test_memory_safety_v155\.py$"),
    re.compile(r"^test_version_contract\.py$"),
)


def _included(path: Path) -> bool:
    return not any(pattern.match(path.name) for pattern in RETIRED_PATTERNS)


def build_suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for path in sorted(TESTS.glob("test_*.py")):
        if _included(path):
            suite.addTests(loader.discover(str(TESTS), pattern=path.name))
    return suite


def main() -> int:
    suite = build_suite()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
