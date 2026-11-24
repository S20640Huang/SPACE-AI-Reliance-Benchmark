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

    def test_interrupted_recovery_requires_matching_journal_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            body = {'input': ['original question']}
            sha = b.digest(b.canonical(body))
            folder = out / 'recovery/prior'
            b.write_json(folder / 'recovery.json', {'items': ['x'], 'results': []})
            b.write_json(folder / 'raw/x.json', {
                'http_status': None, 'transport_error': 'APITimeoutError',
                'request_sha256': sha})
            b.write_json(folder / 'requests/x.json', body)
            b.write_json(out / 'requests/x.json', body)
            self.assertEqual(select_timeouts(out, ['x']), ['x'])
            b.write_json(out / 'requests/x.json', {'input': ['changed']})
            with self.assertRaises(ValueError):
                select_timeouts(out, ['x'])

    def test_connection_and_confirmed_credit_errors_can_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            b.write_json(out / 'raw/connection.json', {
                'http_status': None, 'transport_error': 'APIConnectionError'})
            b.write_json(out / 'raw/credits.json', {
                'http_status': 429,
                'response_text': '{"error": {"code": "credit_balance_exhausted"}}'})
            self.assertEqual(select_timeouts(out, ['connection', 'credits']),
                             ['connection', 'credits'])
            b.write_json(out / 'raw/other.json', {
                'http_status': 429,
                'response_text': '{"error": {"code": "unknown_error"}}'})
            with self.assertRaises(ValueError):
                select_timeouts(out, ['other'])

    def test_recovery_stops_on_failure_without_sdk_retries(self):
        import json
        from contextlib import nullcontext
        import recover_timeouts as recovery
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'runs/test'
            b.write_json(out / 'metadata.json', {'unchanged': True})
            cfg = {'timeout_seconds': 180, 'max_retries': 2}
            job = {'run_id': 'test', 'out': out, 'cfg': cfg,
                   'meta': {'git_commit': 'original'},
                   'items': [{'item_id': i, 'question': []} for i in ['a', 'b', 'c']]}
            for i in ['a', 'b', 'c']:
                b.write_json(out / 'raw' / f'{i}.json', {'http_status': None, 'transport_error': 'APITimeoutError'})
                b.write_json(out / 'requests' / f'{i}.json', {})
            calls = []
            def call(item, *args, **kwargs):
                i = item['item_id']; calls.append(i)
                result = ({'http_status': 200, 'response_text': json.dumps({'status': 'completed'})}
                          if i == 'a' else {'http_status': None, 'transport_error': 'APITimeoutError'})
                b.write_json(out / 'raw' / f'{i}.json', result)
            argv = ['recover_timeouts.py', '--data-root', str(root), '--run-ids', 'test', '--execute']
            with patch('sys.argv', argv), patch.dict('os.environ', {'OPENAI_API_KEY': 'TEST_ONLY'}), \
                 patch.object(recovery, 'prepare', return_value=[job]), \
                 patch.object(b, 'HERE', root), patch.object(b, 'git_commit', return_value='recovery'), \
                 patch.object(recovery, 'verify_body'), patch.object(b, 'make_client', return_value=nullcontext(object())) as client, \
                 patch.object(b, 'call_one', side_effect=call), patch.object(b, 'score'):
                with self.assertRaises(SystemExit):
                    recovery.main()
            self.assertEqual(calls, ['a', 'b'])
            self.assertEqual(client.call_args.args[0]['max_retries'], 0)
            self.assertEqual(client.call_args.args[0]['timeout_seconds'], 900)
            self.assertEqual(b.read_json(out / 'metadata.json'), {'unchanged': True})
