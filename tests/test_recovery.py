import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark as b
from recover_timeouts import select_timeouts, verify_body


class RecoveryTests(unittest.TestCase):
    def test_http200_is_never_selected_even_if_invalid_or_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for i, state in [('ok', 'completed'), ('bad', 'incomplete')]:
                b.write_json(out / 'raw' / f'{i}.json', {'http_status': 200, 'response_text': state})
            b.write_json(out / 'raw/t.json', {'http_status': None, 'transport_error': 'APITimeoutError'})
            self.assertEqual(select_timeouts(out, ['ok', 'bad', 't']), ['t'])

    def test_missing_and_other_errors_are_not_silently_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self.assertRaises(ValueError):
                select_timeouts(out, ['missing'])
            b.write_json(out / 'raw/x.json', {'http_status': 429})
            with self.assertRaises(ValueError):
                select_timeouts(out, ['x'])

    def test_request_identity_is_verified_against_both_saved_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            body = {'model': 'fixed', 'input': ['original question']}
            sha = b.digest(b.canonical(body))
            b.write_json(out / 'raw/x.json', {'request_sha256': sha})
            b.write_json(out / 'requests/x.json', body)
            with patch.object(b, 'build_body', return_value=body):
                self.assertEqual(verify_body({'item_id': 'x', 'question': []}, out, {}, out), sha)
                b.write_json(out / 'requests/x.json', {'input': ['changed question']})
                with self.assertRaises(ValueError):
                    verify_body({'item_id': 'x', 'question': []}, out, {}, out)
