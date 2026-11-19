import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx2
import openai

import benchmark as b
from selection import evaluate_stability, option_group_hash, select_pilot_candidates


def _mock_openai_client(handler):
    return openai.OpenAI(
        api_key='TEST_ONLY',
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


class ReviewTests(unittest.TestCase):
    def test_official_primary_strict_secondary(self):
        for text, gold in [('{"answer":"2"}', 2), ('{"choice":3}', 3), ('{"answer":1} {"answer":4}', 4), ('{"answer":true}', 1)]:
            self.assertEqual(b.upstream_prediction(text), (gold, None))
            self.assertIsNone(b.parse_answer(text)[0])

    def test_parser_exception_is_visible(self):
        self.assertEqual(b.upstream_prediction('{"answer": []}'), ([], None))

    def test_interrupted_request_not_resent_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            b.write_json(out / 'requests/x.json', {})
            called = False

            def handler(req):
                nonlocal called
                called = True
                return httpx2.Response(200, text='{}')

            res = b.call_one({'item_id': 'x'}, Path(tmp), {}, out, client=_mock_openai_client(handler))
            self.assertEqual(res, 'unresolved_prior_attempt_not_resubmitted')
            self.assertFalse(called)

    def test_failed_request_not_resent_without_flag_and_archived_on_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'out'
            cfg = b.read_json(b.HERE / 'config.json')
            cfg['model_snapshot'] = 'gpt-5.4-2026-03-05'
            b.write_json(out / 'raw/x.json', {'http_status': 429, 'response_text': '{"error":"rate"}'})
            calls = []

            def handler(req):
                calls.append(json.loads(req.content.decode('utf-8')))
                return httpx2.Response(
                    200,
                    headers={'x-request-id': 'req_ok', 'content-type': 'application/json'},
                    text='{"status":"completed","model":"gpt-5.4-2026-03-05","output":[{"type":"message","content":[{"type":"output_text","text":"{\\"answer\\": 2}"}]}]}',
                )

            client = _mock_openai_client(handler)
            item = {'item_id': 'x', 'category': 'PTT_vision', 'question': ['Q']}
            self.assertEqual(b.call_one(item, root, cfg, out, client=client, retry_technical_errors=False), 'already_logged')
            self.assertEqual(len(calls), 0)

            self.assertEqual(b.call_one(item, root, cfg, out, client=client, retry_technical_errors=True), 'logged')
            self.assertEqual(len(calls), 1)
            self.assertTrue((out / 'failed_attempts/x.attempt-01.json').is_file())
            self.assertEqual(b.read_json(out / 'raw/x.json')['http_status'], 200)

            # Completed HTTP 200 responses must never be resent even when retry_technical_errors=True.
            self.assertEqual(b.call_one(item, root, cfg, out, client=client, retry_technical_errors=True), 'already_logged')
            self.assertEqual(len(calls), 1)

    def test_no_answer_key_in_actual_network_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = b.read_json(b.HERE / 'config.json')
            cfg['model_snapshot'] = 'gpt-5.4-2026-03-05'
            captured = []

            def handler(req):
                captured.append((dict(req.headers), json.loads(req.content.decode('utf-8'))))
                return httpx2.Response(
                    200,
                    headers={'x-request-id': 'req_1', 'content-type': 'application/json'},
                    text='{"status":"completed","model":"gpt-5.4-2026-03-05","output":[]}',
                )

            with patch.dict('os.environ', {'OPENAI_API_KEY': 'TEST_ONLY'}):
                b.call_one(
                    {'item_id': 'q', 'category': 'PTT_vision', 'question': ['Question with four choices']},
                    root,
                    cfg,
                    root / 'out',
                    client=_mock_openai_client(handler),
                )
            self.assertEqual(len(captured), 1)
            _, payload = captured[0]
            self.assertEqual(payload['input'][0]['content'], [{'type': 'input_text', 'text': 'Question with four choices'}])
            self.assertNotIn('answer', payload)
            self.assertNotIn('TEST_ONLY', (root / 'out/requests/q.json').read_text(encoding='utf-8'))
            self.assertNotIn('TEST_ONLY', (root / 'out/raw/q.json').read_text(encoding='utf-8'))

    def test_primary_denominator_includes_unparseable_and_incomplete_http200(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / 'data'
            (root / 'PTT_vision').mkdir(parents=True)
            (root / 'PTT_vision/qas.json').write_text(json.dumps([{'question': ['q'], 'answer': 2}] * 3), encoding='utf-8')
            _, _, files = b.load_pool(root, ['PTT_vision'])
            out = home / 'runs/test'
            ids = ['PTT_vision-00000', 'PTT_vision-00001', 'PTT_vision-00002']
            b.write_json(out / 'metadata.json', {'source_files': files, 'config': {'categories': ['PTT_vision']}, 'item_ids': ids})
            responses = [
                {'status': 'completed', 'model': 'gpt-5.4-2026-03-05', 'usage': {'input_tokens': 50, 'output_tokens': 120, 'output_tokens_details': {'reasoning_tokens': 100}}, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"answer":"2"}'}]}]},
                {'status': 'completed', 'model': 'gpt-5.4-2026-03-05', 'usage': {'input_tokens': 50, 'output_tokens': 80, 'output_tokens_details': {'reasoning_tokens': 60}}, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'no answer'}]}]},
                {'status': 'incomplete', 'model': 'gpt-5.4-2026-03-05', 'incomplete_details': {'reason': 'max_output_tokens'}, 'usage': {'input_tokens': 50, 'output_tokens': 4096, 'output_tokens_details': {'reasoning_tokens': 4096}}, 'output': []},
            ]
            for ident, resp in zip(ids, responses):
                b.write_json(out / 'raw' / f'{ident}.json', {'http_status': 200, 'response_text': json.dumps(resp)})
            with patch.object(b, 'HERE', home):
                b.score(root, {}, 'test')
            result = b.read_json(out / 'summary.json')['PTT_vision']
            self.assertAlmostEqual(result['upstream_accuracy_full_pool'], 1 / 3)
            self.assertIsNone(result['upstream_accuracy_completed_only_gate'])
            self.assertEqual(result['n_incomplete'], 1)
            self.assertEqual(result['n_valid'], 0)
            self.assertTrue(result['single_served_model'])
            self.assertEqual(result['max_reasoning_tokens_observed'], 4096)

    def test_permutation_deduplication_and_stability_filter(self):
        g1 = option_group_hash(['Choose one: 1) north 2) south 3) east 4) west'], ['imgA'])
        g2 = option_group_hash(['Choose one: 1) east 2) north 3) west 4) south'], ['imgA'])
        self.assertEqual(g1, g2)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            items_csv = base / 'items.csv'
            with items_csv.open('w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['item_id', 'category', 'image_sha256', 'option_group_sha256'])
                w.writeheader()
                # Two 2-variant permutation groups in JLO_vision: group A (correct) and group B (incorrect)
                for i, grp in enumerate(['grpA', 'grpA', 'grpB', 'grpB']):
                    w.writerow({'item_id': f'JLO_vision-{i:05d}', 'category': 'JLO_vision', 'image_sha256': 'i1;i2', 'option_group_sha256': grp})

            runs_dir = base / 'runs'
            sci_cfg = {'categories': ['JLO_vision'], 'model_snapshot': 'gpt-5.4-2026-03-05', 'reasoning_effort': 'medium', 'max_output_tokens': 16384, 'image_detail': 'low'}
            src_files = [{'category': 'JLO_vision', 'records': 4, 'qas_sha256': 'abc'}]
            for idx, rid in enumerate(['full-001', 'r2', 'r3', 'r4', 'r5']):
                rdir = runs_dir / rid
                b.write_json(rdir / 'metadata.json', {'config': sci_cfg, 'source_files': src_files})
                with (rdir / 'scores.csv').open('w', encoding='utf-8', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=['item_id', 'category', 'parsed_answer', 'gold_answer', 'status', 'strict_correct'])
                    w.writeheader()
                    for i in range(4):
                        is_grp_a = i < 2
                        # Group A is stable correct (5/5); Group B flips in r3,r4,r5 (only 2/5 agree -> unstable)
                        if is_grp_a:
                            ans, corr = 2, 1
                        else:
                            ans = 3 if idx < 2 else 2
                            corr = 0 if idx < 2 else 1
                        w.writerow({'item_id': f'JLO_vision-{i:05d}', 'category': 'JLO_vision', 'parsed_answer': ans, 'gold_answer': 2, 'status': 'valid', 'strict_correct': corr})

            cand_path = base / 'candidates.json'
            sel = select_pilot_candidates(runs_dir / 'full-001' / 'scores.csv', items_csv, per_category=2, seed=42, out_path=cand_path)
            cands = b.read_json(cand_path)
            self.assertEqual(len(cands), 2)
            self.assertEqual(sel['categories']['JLO_vision']['selected_correct'], 1)
            self.assertEqual(sel['categories']['JLO_vision']['selected_incorrect'], 1)

            stab_out = base / 'stability.json'
            stab = evaluate_stability(runs_dir, 'full-001', ['r2', 'r3', 'r4', 'r5'], cand_path, min_agreement=4, out_path=stab_out)
            self.assertEqual(stab['total_candidates'], 2)
            self.assertEqual(stab['total_stable'], 1)


if __name__ == '__main__':
    unittest.main()
