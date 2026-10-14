import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class VeoRecoveryWiringTests(unittest.TestCase):
    def test_recovery_patch_applies_after_production_veo_patches(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shutil.copy2(repo / "main.py", root / "main.py")
            for name in (
                "main_veo.patch",
                "main_veo_start_guard.patch",
                "main_veo_recovery.patch",
            ):
                patch_file = repo / "ops" / name
                result = subprocess.run(
                    ["patch", "--batch", "--forward", "-p1"],
                    cwd=root,
                    input=patch_file.read_bytes(),
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
            patched = (root / "main.py").read_text(encoding="utf-8")
            self.assertIn("veoresume:", patched)
            self.assertIn("resume_only=resume_only", patched)
            self.assertIn("закончились предоплаченные кредиты Google AI Studio", patched)
            self.assertIn("https://ai.studio/projects", patched)

    def test_docker_applies_recovery_after_start_guard(self):
        dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
        self.assertLess(
            dockerfile.index("main_veo_start_guard.patch"),
            dockerfile.index("main_veo_recovery.patch"),
        )


if __name__ == "__main__":
    unittest.main()
