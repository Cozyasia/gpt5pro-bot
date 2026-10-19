"""Registration retry/redaction checks with mocked HTTP only."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from scripts.v265_metahuman_evaluation_access import main


class EvaluationAccessTests(unittest.TestCase):
    def invoke(self,path):
        env={'V265_EVALUATION_NAME':'Test','V265_EVALUATION_EMAIL':'test@example.invalid'}
        with patch.dict(os.environ,env,clear=True),patch('sys.argv',['access','--secret-file',str(path)]):
            main()

    def test_transient_failure_is_bounded_and_removes_empty_secret(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'token'; log=io.StringIO()
            failures=[HTTPError('https://example.invalid',504,'private error',{},None) for _ in range(3)]
            with patch('urllib.request.urlopen',side_effect=failures) as request,patch('time.sleep') as sleep,contextlib.redirect_stdout(log):
                with self.assertRaises(SystemExit): self.invoke(path)
            self.assertEqual(request.call_count,3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list],[3,8])
            self.assertFalse(path.exists())
            self.assertNotIn('private error',log.getvalue())

    def test_token_is_owner_only_and_never_logged(self):
        response=io.BytesIO(b'{"result":{"token":"synthetic-test-secret"}}');response.status=200
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'token';log=io.StringIO()
            with patch('urllib.request.urlopen',return_value=response),contextlib.redirect_stdout(log): self.invoke(path)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(path.read_text().strip(),'synthetic-test-secret')
            self.assertNotIn('synthetic-test-secret',log.getvalue())
