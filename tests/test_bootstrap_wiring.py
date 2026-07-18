# -*- coding: utf-8 -*-
from pathlib import Path
import unittest


class BootstrapWiringTests(unittest.TestCase):
    def test_secret_loader_explicitly_starts_production_layer(self):
        source = Path("secret_loader.py").read_text(encoding="utf-8")
        self.assertIn("from neyrobot_prod.bootstrap import install_early", source)
        self.assertIn("_install_production_hardening()", source)

    def test_secret_loader_explicitly_starts_version_contract(self):
        source = Path("secret_loader.py").read_text(encoding="utf-8")
        self.assertIn("from neyrobot_prod.versioning import install_early", source)
        self.assertIn("_install_version_contract()", source)

    def test_render_entrypoint_imports_secret_loader_before_runtime_config(self):
        source = Path("main.py").read_text(encoding="utf-8")
        bootstrap_pos = source.find("from secret_loader import bootstrap_secret_environment")
        token_pos = source.find("BOT_TOKEN =")
        self.assertGreaterEqual(bootstrap_pos, 0)
        self.assertGreater(token_pos, bootstrap_pos)


if __name__ == "__main__":
    unittest.main()
