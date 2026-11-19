import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import benchmark as b


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.cfg = b.read_json(b.HERE / 'config.json')

    def test_gold_answer_cannot_change_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'PTT_vision').mkdir()
            p = root / 'PTT_vision' / 'qas.json'
            row = {'question': ['Choose one: 1) A 2) B 3) C 4) D', 'Return JSON with answer.'], 'answer': 1, 'task': 'MRT (vision)'}
            p.write_text(json.dumps([row]), encoding='utf-8')
            first, key1, _ = b.load_pool(root, ['PTT_vision'])
            request1 = b.build_body(first[0]['question'], root, self.cfg)
            row['answer'] = 4
            row['task'] = 'SECRET_METADATA_SENTINEL'
            p.write_text(json.dumps([row]), encoding='utf-8')
            second, key2, _ = b.load_pool(root, ['PTT_vision'])
            request2 = b.build_body(second[0]['question'], root, self.cfg)
            self.assertNotEqual(key1, key2)
            self.assertEqual(request1, request2)
            self.assertNotIn('SECRET_METADATA_SENTINEL', json.dumps(request2))
            self.assertEqual(first[0]['category'], 'PTT_vision')

    def test_parser(self):
        self.assertEqual(b.parse_answer('Reasoning\n```json\n{"answer": 2}\n```'), (2, 'valid'))
        for txt in ['2', '{"answer": "2"}', '{"answer": true}', '{"answer": 5}', '{"answer": 1} {"answer": 2}']:
            self.assertIsNone(b.parse_answer(txt)[0])

    def test_image_marker_replaced_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'PTT_vision').mkdir()
            __import__('PIL.Image', fromlist=['Image']).new('RGB', (2, 2), (255, 0, 0)).save(root / 'PTT_vision' / 'a.png')
            body = b.build_body(['before', 'IMAGE:data/SPACE_data_release/PTT_vision/a.png', 'after'], root, self.cfg)
            c = body['input'][0]['content']
            self.assertEqual([x['type'] for x in c], ['input_text', 'input_image', 'input_text'])
            self.assertTrue(c[1]['image_url'].startswith('data:image/jpeg;base64,'))
            self.assertEqual(c[2]['text'], 'after')
            self.assertNotIn('previous_response_id', body)

    def test_draft_blocks_live_requests(self):
        with patch.object(b, 'make_client') as client_factory:
            with self.assertRaises(ValueError):
                b.validate_live(self.cfg)
            client_factory.assert_not_called()

    def test_gitignore_excludes_local_runs_and_data(self):
        for rel in ('local/request_preview.json', 'runs/full-001/metadata.json', 'data/SPACE_data_release/MRT_vision/qas.json'):
            res = subprocess.run(['git', 'check-ignore', '-q', rel], cwd=b.HERE)
            self.assertEqual(res.returncode, 0, f'{rel} must be ignored by git')

    def test_missing_results_not_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'dataset'
            (root / 'PTT_vision').mkdir(parents=True)
            (root / 'PTT_vision' / 'qas.json').write_text(json.dumps([{'question': ['q'], 'answer': 2}]), encoding='utf-8')
            _, _, files = b.load_pool(root, ['PTT_vision'])
            home = Path(tmp) / 'project'
            out = home / 'runs' / 'test'
            out.mkdir(parents=True)
            b.write_json(
                out / 'metadata.json',
                {'config': {'categories': ['PTT_vision']}, 'source_files': files, 'item_ids': ['PTT_vision-00000']},
            )
            with patch.object(b, 'HERE', home):
                b.score(root, self.cfg, 'test')
            s = b.read_json(out / 'summary.json')['PTT_vision']
            self.assertEqual(s['n_expected'], 1)
            self.assertEqual(s['status_counts'], {'missing': 1})
            self.assertIsNone(s['accuracy_valid_only'])


if __name__ == '__main__':
    unittest.main()
