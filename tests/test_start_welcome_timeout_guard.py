import unittest
from pathlib import Path


class StartWelcomeTimeoutGuardTests(unittest.TestCase):
    def test_docker_applies_welcome_timeout_guard(self):
        dockerfile = Path(__file__).parents[1].joinpath("Dockerfile").read_text(encoding="utf-8")
        self.assertIn("main_start_welcome.patch", dockerfile)
        self.assertLess(
            dockerfile.index("main_veo_start_guard.patch"),
            dockerfile.index("main_start_welcome.patch"),
        )

    def test_timeout_delivery_outcome_suppresses_fallback(self):
        patch = Path(__file__).parents[1].joinpath("ops/main_start_welcome.patch").read_text(
            encoding="utf-8"
        )
        self.assertIn("except (TimedOut, asyncio.TimeoutError) as e:", patch)
        self.assertIn("suppressing fallback", patch)
        guarded = patch.split("except (TimedOut, asyncio.TimeoutError) as e:", 1)[1].split(
            "except Exception as e:", 1
        )[0]
        self.assertIn("return", guarded)


if __name__ == "__main__":
    unittest.main()
