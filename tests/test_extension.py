import csv
import json
import tempfile
import unittest
from pathlib import Path

from selection import select_pilot_candidates


class ExtensionTests(unittest.TestCase):
    def test_excludes_whole_layout_and_filters_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [
                ('a', 'MPFB_vision', 'old', 0),
                ('b', 'MPFB_vision', 'old', 1),
                ('c', 'MPFB_vision', 'new1', 0),
                ('d', 'MPFB_vision', 'new2', 1),
                ('e', 'MRT_vision', 'other', 0),
            ]
            with (root / 'items.csv').open('w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['item_id', 'category', 'layout_family_sha256', 'image_sha256'])
                w.writerows((i, c, g, g) for i, c, g, v in rows)
            with (root / 'scores.csv').open('w', newline='') as f:
                w = csv.writer(f)
                w.writerow(['item_id', 'status', 'strict_correct'])
                w.writerows((i, 'valid', v) for i, c, g, v in rows)
            excluded = root / 'excluded.json'
            excluded.write_text('["a"]')
            out = root / 'selected.json'
            def select(**kwargs):
                return select_pilot_candidates(root / 'scores.csv', root / 'items.csv', 2, 20261119, out, **kwargs)
            result = select(exclude_ids=excluded, categories=['MPFB_vision'])
            self.assertEqual(json.loads(out.read_text()), ['c', 'd'])
            self.assertEqual(result['categories']['MPFB_vision']['selected_correct'], 1)
            first = out.read_bytes()
            select(exclude_ids=excluded, categories=['MPFB_vision'])
            self.assertEqual(out.read_bytes(), first)
            for categories in ([], ['typo']):
                with self.assertRaises(ValueError):
                    select(categories=categories)
            for value in ('["unknown"]', '{"a":true}', '[1]'):
                excluded.write_text(value)
                with self.assertRaises(ValueError):
                    select(exclude_ids=excluded)

    def test_frozen_extension_is_disjoint_by_layout(self):
        root = Path(__file__).resolve().parents[1]
        folder = root / 'manifests/mpfb_extension_2026-11-23'
        with (root / 'manifests/items.csv').open() as f:
            items = {r['item_id']: r for r in csv.DictReader(f)}
        old = json.loads((folder / 'excluded_original_candidate_ids.json').read_text())
        new = json.loads((folder / 'candidate_ids.json').read_text())
        all_layouts = {r['layout_family_sha256'] for r in items.values() if r['category'] == 'MPFB_vision'}
        old_layouts = {items[i]['layout_family_sha256'] for i in old if items[i]['category'] == 'MPFB_vision'}
        new_layouts = {items[i]['layout_family_sha256'] for i in new}
        self.assertEqual(len(new), 10)
        self.assertEqual(len(new_layouts), 10)
        self.assertEqual(new_layouts, all_layouts - old_layouts)
        self.assertTrue(all(items[i]['category'] == 'MPFB_vision' for i in new))
