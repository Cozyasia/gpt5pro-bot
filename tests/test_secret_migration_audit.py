import tempfile
import unittest
from pathlib import Path

from scripts.audit_secret_migration import audit


class SecretMigrationAuditTests(unittest.TestCase):
    def test_counts_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "neyro_bot.env"
            path.write_text("TOKEN=secret-test-value\nMODEL=test-model\nEMPTY=\nTOKEN=second-value\n", encoding="utf-8")
            result = audit(str(path), {"TOKEN": "already-set"})
            self.assertEqual(result, {"file_found": True, "file_entries": 3, "env_overrides": 1, "file_only": 2, "empty_entries": 1, "duplicate_names": 1})
            self.assertNotIn("secret-test-value", str(result))

    def test_missing_file_is_nonfatal(self):
        self.assertFalse(audit("/missing/file", {})["file_found"])


if __name__ == "__main__":
    unittest.main()
