import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from scripts.inspect_billing_contract import inspect
class InspectionTests(unittest.TestCase):
    def test_does_not_print_secret_literals(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"source.py"
            p.write_text("SECRET='sensitive-secret'\ndef _credits_to_usd(x):\n    return x/10\n")
            out=StringIO()
            with redirect_stdout(out): inspect(p)
            self.assertIn("DEF _credits_to_usd",out.getvalue())
            self.assertNotIn("sensitive-secret",out.getvalue())
if __name__=="__main__": unittest.main()
