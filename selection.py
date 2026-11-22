"""Stimulus-family grouping, stratified pilot preselection, and 5-run stability filtering."""
import csv
import hashlib
import json
import random
import re
from pathlib import Path

INLINE_CHOICE_RE = re.compile(r'(?:^|\s+)(?:option\s*)?[\(\[]?([1-4])[\)\].:]\s+', re.IGNORECASE)
LINE_CHOICE_RE = re.compile(r'^\s*(?:option\s*)?[\(\[]?[1-4][\)\].:]\s*(.+?)\s*$', re.IGNORECASE)


def _digest_json(obj) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _normalize_text_segment(segment: str):
    lines = segment.splitlines()
    out_lines = []
    option_buf = []
    for line in lines:
        m = LINE_CHOICE_RE.match(line)
        if m:
            option_buf.append(m.group(1).strip())
            continue
        if option_buf:
            out_lines.append({'options': sorted(option_buf)})
            option_buf = []
        matches = list(INLINE_CHOICE_RE.finditer(line))
        if [m.group(1) for m in matches] == ['1', '2', '3', '4']:
            stem = line[:matches[0].start()].strip()
            opts = []
            for idx, match in enumerate(matches):
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
                opts.append(line[match.end():end].strip())
            out_lines.append({'stem': stem, 'options': sorted(opts)})
        else:
            out_lines.append(line.strip())
    if option_buf:
        out_lines.append({'options': sorted(option_buf)})
    return out_lines


def option_group_hash(question: list[str], img_hashes: list[str]) -> str:
    if len(img_hashes) >= 5:
        text_parts = [s.strip() for s in question if not s.startswith('IMAGE:')]
        return _digest_json({
            'mode': 'image_options',
            'text': text_parts,
            'stem_image': img_hashes[0],
            'option_images': sorted(img_hashes[1:]),
        })
    segments = [_normalize_text_segment(s) for s in question if not s.startswith('IMAGE:')]
    return _digest_json({'mode': 'text_options', 'segments': segments, 'images': img_hashes})


def _write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def select_pilot_candidates(
    scores_csv: Path,
    items_csv: Path,
    per_category: int,
    seed: int,
    out_path: Path,
    data_root: Path | None = None,
) -> dict:
    if per_category <= 0:
        raise ValueError('per_category must be positive')
    with Path(scores_csv).open(encoding='utf-8', newline='') as f:
        score_rows = {r['item_id']: r for r in csv.DictReader(f)}
    with Path(items_csv).open(encoding='utf-8', newline='') as f:
        manifest_rows = list(csv.DictReader(f))

    computed_groups = {}
    if data_root is not None:
        categories = sorted({r['category'] for r in manifest_rows})
        qas_by_id = {}
        for cat in categories:
            qas = json.loads((Path(data_root) / cat / 'qas.json').read_text(encoding='utf-8'))
            for i, rec in enumerate(qas):
                qas_by_id[f'{cat}-{i:05d}'] = rec['question']
        for r in manifest_rows:
            imgs = [x for x in r['image_sha256'].split(';') if x]
            computed_groups[r['item_id']] = option_group_hash(qas_by_id[r['item_id']], imgs)

    by_cat_group: dict[str, dict[str, list[dict]]] = {}
    for mrow in manifest_rows:
        item_id = mrow['item_id']
        cat = mrow['category']
        srow = score_rows.get(item_id)
        if not srow or srow.get('status') != 'valid':
            continue
        imgs = [x for x in mrow['image_sha256'].split(';') if x]
        if cat == 'JLO_vision':
            group_key = mrow.get('layout_family_sha256')
            if not group_key:
                raise ValueError(f'JLO item {item_id} requires layout_family_sha256; rerun audit.')
        else:
            # PTT groups represent distinct perspective questions, not entire scenes.
            group_key = mrow.get('option_group_sha256') or computed_groups.get(item_id)
        if not group_key:
            if len(imgs) <= 1:
                raise ValueError(
                    f'Item {item_id} requires option_group_sha256 in items.csv or --data-root to deduplicate text options.'
                )
            group_key = _digest_json(sorted(set(imgs)))
        by_cat_group.setdefault(cat, {}).setdefault(group_key, []).append(srow)

    rng = random.Random(seed)
    selected_ids = []
    summary = {'seed': seed, 'per_category_target': per_category, 'categories': {}}
    for cat in sorted(by_cat_group):
        groups = by_cat_group[cat]
        representatives = []
        for group_key in sorted(groups):
            members = sorted(groups[group_key], key=lambda x: x['item_id'])
            representatives.append(rng.choice(members))
        correct = sorted([r for r in representatives if int(r['strict_correct']) == 1], key=lambda x: x['item_id'])
        incorrect = sorted([r for r in representatives if int(r['strict_correct']) == 0], key=lambda x: x['item_id'])
        rng.shuffle(correct)
        rng.shuffle(incorrect)
        half = per_category // 2
        other = per_category - half
        take_c = min(len(correct), half)
        take_i = min(len(incorrect), other)
        if take_c < half:
            take_i = min(len(incorrect), per_category - take_c)
        elif take_i < other:
            take_c = min(len(correct), per_category - take_i)
        picked = sorted([r['item_id'] for r in (correct[:take_c] + incorrect[:take_i])])
        selected_ids.extend(picked)
        summary['categories'][cat] = {
            'grouping_field': 'layout_family_sha256' if cat == 'JLO_vision' else 'option_group_sha256',
            'unique_valid_groups': len(representatives),
            'available_correct_groups': len(correct),
            'available_incorrect_groups': len(incorrect),
            'selected_total': len(picked),
            'selected_correct': take_c,
            'selected_incorrect': take_i,
        }

    selected_ids.sort()
    _write_json(out_path, selected_ids)
    _write_json(Path(out_path).with_suffix('.summary.json'), summary)
    return summary


def evaluate_stability(
    runs_dir: Path,
    base_run_id: str,
    repeat_run_ids: list[str],
    candidate_ids_path: Path,
    min_agreement: int,
    out_path: Path,
) -> dict:
    if len(repeat_run_ids) != 4 or len(set(repeat_run_ids)) != 4 or base_run_id in set(repeat_run_ids):
        raise ValueError('Exactly 4 distinct repeat_run_ids different from base_run_id are required.')
    if min_agreement not in (1, 2, 3, 4, 5):
        raise ValueError('min_agreement must be between 1 and 5.')
    all_runs = [base_run_id, *repeat_run_ids]
    scientific_keys = ('categories', 'model_snapshot', 'reasoning_effort', 'max_output_tokens', 'image_detail')
    metas = [json.loads((Path(runs_dir) / rid / 'metadata.json').read_text(encoding='utf-8')) for rid in all_runs]
    base_sig = {k: metas[0]['config'].get(k) for k in scientific_keys}
    for rid, meta in zip(repeat_run_ids, metas[1:]):
        sig = {k: meta['config'].get(k) for k in scientific_keys}
        if sig != base_sig or meta['source_files'] != metas[0]['source_files']:
            raise ValueError(f'Scientific settings or source files differ in {rid}')

    scores_by_run = []
    for rid in all_runs:
        with (Path(runs_dir) / rid / 'scores.csv').open(encoding='utf-8', newline='') as f:
            scores_by_run.append({r['item_id']: r for r in csv.DictReader(f)})

    candidate_ids = json.loads(Path(candidate_ids_path).read_text(encoding='utf-8'))
    rows = []
    for item_id in candidate_ids:
        r1 = scores_by_run[0].get(item_id)
        if not r1:
            raise ValueError(f'Candidate {item_id} missing from base run {base_run_id}')
        r1_valid = r1['status'] == 'valid'
        r1_correct = int(r1['strict_correct']) if r1_valid else None
        r1_answer = int(r1['parsed_answer']) if r1_valid else None
        valid_runs = 0
        corr_agree = 0
        opt_agree = 0
        for run_map in scores_by_run:
            rr = run_map.get(item_id)
            if rr and rr['status'] == 'valid':
                valid_runs += 1
                if r1_valid and int(rr['strict_correct']) == r1_correct:
                    corr_agree += 1
                if r1_valid and int(rr['parsed_answer']) == r1_answer:
                    opt_agree += 1
        stable = bool(r1_valid and corr_agree >= min_agreement)
        rows.append({
            'item_id': item_id,
            'category': r1['category'],
            'run1_valid': int(r1_valid),
            'run1_advice_option': r1_answer if r1_valid else '',
            'gold_answer': int(r1['gold_answer']),
            'run1_correct': r1_correct if r1_valid else '',
            'n_valid_runs': valid_runs,
            'correctness_agreement_of_5': corr_agree,
            'exact_option_agreement_of_5': opt_agree,
            'stable': int(stable),
        })

    csv_path = Path(out_path).with_suffix('.csv')
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    categories = sorted({r['category'] for r in rows})
    summary = {
        'base_run_id': base_run_id,
        'repeat_run_ids': repeat_run_ids,
        'min_agreement': min_agreement,
        'total_candidates': len(rows),
        'total_stable': sum(r['stable'] for r in rows),
        'stable_item_ids': [r['item_id'] for r in rows if r['stable']],
        'categories': {},
    }
    for cat in categories:
        cr = [r for r in rows if r['category'] == cat]
        st = [r for r in cr if r['stable']]
        summary['categories'][cat] = {
            'n_candidates': len(cr),
            'n_stable': len(st),
            'n_stable_ai_correct': sum(r['run1_correct'] == 1 for r in st),
            'n_stable_ai_incorrect': sum(r['run1_correct'] == 0 for r in st),
            'mean_exact_option_agreement_of_5': sum(r['exact_option_agreement_of_5'] for r in cr) / len(cr) if cr else None,
        }
    _write_json(out_path, summary)
    return summary
