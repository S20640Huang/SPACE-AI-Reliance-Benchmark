"""SPACE visual QA benchmark runner, scorer, and stimulus selector.
Adapted upstream QA loading and scoring; see docs/UPSTREAM.md for declared differences.
"""
import argparse
import concurrent.futures
import contextlib
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import openai
from selection import evaluate_stability, option_group_hash, select_pilot_candidates
from space_adapter import load_question_content
from vendor.space_functions import parse_answer_from_response

HERE = Path(__file__).resolve().parent


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path: Path, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def image_path(marker: str, root: Path) -> Path:
    prefix = 'IMAGE:data/SPACE_data_release/'
    if not marker.startswith(prefix):
        raise ValueError('Unsupported image marker; inspect upstream format')
    p = (Path(root) / marker[len(prefix):]).resolve()
    if Path(root).resolve() not in p.parents or not p.is_file():
        raise ValueError('Image missing or outside dataset root: ' + marker)
    return p


def load_pool(root: Path, categories: list[str]):
    """Split model inputs and scoring keys immediately at the loader boundary."""
    inputs, keys, files = [], {}, []
    root = Path(root)
    for cat in categories:
        path = root / cat / 'qas.json'
        raw = path.read_bytes()
        records = json.loads(raw.decode('utf-8'))
        files.append({'category': cat, 'records': len(records), 'qas_sha256': digest(raw)})
        for i, record in enumerate(records):
            q, answer = record['question'], record['answer']
            if not isinstance(q, list) or not all(isinstance(s, str) for s in q):
                raise ValueError('Unsupported question schema')
            if type(answer) is not int or answer not in (1, 2, 3, 4):
                raise ValueError('Unsupported answer')
            item_id = f'{cat}-{i:05d}'
            # Never pass the original record, its answer, or its task field to the request builder.
            inputs.append({'item_id': item_id, 'category': cat, 'question': list(q)})
            keys[item_id] = answer
    return inputs, keys, files


def content_for(question: list[str], root: Path, detail: str):
    source = load_question_content(question, root, 'gpt-compat', detail)
    if isinstance(source, str):
        source = [source]
    # Representation-only conversion from the upstream mixed content to Responses.
    content = []
    for part in source:
        if isinstance(part, str):
            content.append({'type': 'input_text', 'text': part})
        else:
            content.append({
                'type': 'input_image',
                'image_url': part['image_url']['url'],
                'detail': part['image_url']['detail'],
            })
    return content


def build_body(question: list[str], root: Path, config: dict) -> dict:
    # Allowlist: the question alone crosses this interface. No gold-answer argument exists.
    body = {
        'model': config['model_snapshot'],
        'input': [{'role': 'user', 'content': content_for(question, root, config['image_detail'])}],
        'store': False,
    }
    if config['reasoning_effort'] is not None:
        body['reasoning'] = {'effort': config['reasoning_effort']}
    if config['max_output_tokens'] is not None:
        body['max_output_tokens'] = config['max_output_tokens']
    return body


def parse_answer(text: str):
    """Allow surrounding reasoning/fences; reject conflicting/malformed answer objects."""
    decoder = json.JSONDecoder()
    candidates = []
    for match in re.finditer(r'\{', text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and 'answer' in obj:
            candidates.append(obj['answer'])
    if not candidates:
        return None, 'no_json_answer'
    if any(type(v) is not int or v not in (1, 2, 3, 4) for v in candidates):
        return None, 'invalid_answer_value'
    if len(set(candidates)) != 1:
        return None, 'conflicting_answers'
    return candidates[0], 'valid'


def upstream_prediction(text: str):
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            return parse_answer_from_response(text), None
        except Exception as exc:
            # Official parser may raise for unusual values.
            return None, type(exc).__name__


def environment_versions() -> dict[str, str]:
    return {p: importlib.metadata.version(p) for p in ('Pillow', 'numpy', 'openai')}


def output_text(response: dict) -> str:
    return '\n'.join(
        part.get('text', '')
        for item in response.get('output', [])
        if item.get('type') == 'message'
        for part in item.get('content', [])
        if part.get('type') == 'output_text'
    )


def audit(root: Path, cfg: dict) -> None:
    inputs, _, files = load_pool(root, cfg['categories'])
    rows, seen, dup = [], {}, 0
    for item in inputs:
        img_hashes = [digest(image_path(x, root).read_bytes()) for x in item['question'] if x.startswith('IMAGE:')]
        signature = digest(canonical({'question': item['question'], 'images': img_hashes}))
        duplicate_of = seen.get(signature, '')
        dup += bool(duplicate_of)
        seen.setdefault(signature, item['item_id'])
        layout_family = img_hashes[0] if img_hashes else ''
        option_group = option_group_hash(item['question'], img_hashes)
        rows.append({
            'item_id': item['item_id'],
            'category': item['category'],
            'question_sha256': digest(canonical(item['question'])),
            'image_sha256': ';'.join(img_hashes),
            'layout_family_sha256': layout_family,
            'option_group_sha256': option_group,
            'exact_duplicate_of': duplicate_of,
        })
    out = HERE / 'manifests' / 'items.csv'
    with out.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    family_counts = {
        cat: {
            'records': sum(r['category'] == cat for r in rows),
            'unique_layout_families': len({r['layout_family_sha256'] for r in rows if r['category'] == cat}),
            'unique_option_groups': len({r['option_group_sha256'] for r in rows if r['category'] == cat}),
        }
        for cat in cfg['categories']
    }
    write_json(
        HERE / 'manifests' / 'inventory.json',
        {
            'source_files': files,
            'total_records': len(rows),
            'exact_duplicate_records': dup,
            'category_grouping': family_counts,
            'note': 'All source records retained for full-pool pass. Use option_group_sha256 and layout_family_sha256 to deduplicate variants before pilot and learning/retention splits.',
        },
    )
    # Local-only request preview, excluded by .gitignore.
    preview = build_body(inputs[0]['question'], root, cfg)
    for part in preview['input'][0]['content']:
        if part['type'] == 'input_image':
            part['image_url'] = '[image bytes omitted from preview]'
    write_json(HERE / 'local' / 'request_preview.json', preview)
    print(json.dumps({'records': len(rows), 'exact_duplicate_records': dup, 'category_grouping': family_counts, 'network_requests': 0}))


def git_commit() -> str:
    p = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=HERE, capture_output=True, text=True)
    if p.returncode:
        raise ValueError('Commit this repository before a live run.')
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=HERE, capture_output=True, text=True, check=True)
    if status.stdout.strip():
        raise ValueError('Working tree has uncommitted changes; commit first.')
    return p.stdout.strip()


def validate_live(cfg: dict) -> None:
    if sys.version_info < (3, 15):
        raise ValueError('Python 3.15 or newer is required for live execution.')
    if not cfg['model_settings_verified'] or not cfg['upstream_implementation_checked'] or not cfg.get('failure_policy_approved'):
        raise ValueError('Draft blocked: verify model settings and upstream implementation first.')
    if not cfg['upstream_commit'] or not re.fullmatch(r'[0-9a-f]{40}', cfg['upstream_commit']):
        raise ValueError('Record the actual 40-character upstream commit.')
    if not cfg['model_snapshot'] or not isinstance(cfg['model_snapshot'], str):
        raise ValueError('Specify a verified model ID.')
    if not cfg.get('allow_undated_model_id', False) and not re.search(r'\d{4}-\d{2}-\d{2}', cfg['model_snapshot']):
        raise ValueError('A verified dated model snapshot is required unless allow_undated_model_id is explicitly enabled.')
    if type(cfg['max_output_tokens']) is not int or cfg['max_output_tokens'] <= 0:
        raise ValueError('Verify and specify an adequate output-token limit.')
    max_retries = cfg.get('max_retries', 0)
    if type(max_retries) is not int or max_retries < 0:
        raise ValueError('max_retries must be a non-negative integer.')
    if cfg['status'] != 'ready':
        raise ValueError('Config status must be ready after review.')
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('Set OPENAI_API_KEY locally; never place it in config.json.')


def make_client(cfg: dict) -> openai.OpenAI:
    return openai.OpenAI(
        api_key=os.environ['OPENAI_API_KEY'],
        timeout=cfg.get('timeout_seconds', 180),
        max_retries=cfg.get('max_retries', 2),
    )


def _archive_prior_failure(source_path: Path, failed_dir: Path, stem: str) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    idx = 1
    while (failed_dir / f'{stem}.attempt-{idx:02d}.json').exists():
        idx += 1
    source_path.replace(failed_dir / f'{stem}.attempt-{idx:02d}.json')


def call_one(
    item: dict,
    root: Path,
    cfg: dict,
    out: Path,
    client: openai.OpenAI | None = None,
    retry_technical_errors: bool = False,
) -> str:
    dest = out / 'raw' / (item['item_id'] + '.json')
    req_path = out / 'requests' / (item['item_id'] + '.json')
    failed_dir = out / 'failed_attempts'
    if dest.exists():
        existing = read_json(dest)
        if existing.get('http_status') == 200 or not retry_technical_errors:
            return 'already_logged'
        _archive_prior_failure(dest, failed_dir, item['item_id'])
        if req_path.exists():
            req_path.unlink()
    elif req_path.exists():
        if not retry_technical_errors:
            return 'unresolved_prior_attempt_not_resubmitted'
        _archive_prior_failure(req_path, failed_dir, item['item_id'] + '.interrupted')

    body = build_body(item['question'], root, cfg)
    request_hash = digest(canonical(body))
    # Immutable per-item request archived locally, without headers or credentials.
    write_json(req_path, body)
    record = {
        'item_id': item['item_id'],
        'category': item['category'],
        'request_sha256': request_hash,
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    active_client = client if client is not None else make_client(cfg)
    try:
        raw_resp = active_client.responses.with_raw_response.create(**body)
        record.update(
            http_status=raw_resp.status_code,
            response_text=raw_resp.text,
            request_id=raw_resp.headers.get('x-request-id'),
        )
    except openai.APIStatusError as err:
        record.update(
            http_status=err.status_code,
            response_text=err.response.text,
            request_id=err.request_id,
        )
    except (openai.APITimeoutError, openai.APIConnectionError) as err:
        record.update(http_status=None, transport_error=type(err).__name__, error_message=str(err))
    write_json(dest, record)
    return 'logged'


def run(root: Path, cfg: dict, args) -> None:
    validate_live(cfg)
    commit = git_commit()
    inputs, _, files = load_pool(root, cfg['categories'])
    if args.phase != 'repeat' and args.repeat_number != 1:
        raise ValueError('Technical/full runs use repeat-number 1')
    if args.phase == 'technical':
        inputs = [x for cat in cfg['categories'] for x in [y for y in inputs if y['category'] == cat][:2]]
    elif args.phase == 'repeat':
        if not args.candidate_ids or args.repeat_number not in (2, 3, 4, 5):
            raise ValueError('Repeat phase requires frozen candidate IDs and repeat number 2-5.')
        ids = read_json(Path(args.candidate_ids))
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or not set(ids) <= {x['item_id'] for x in inputs}:
            raise ValueError('Invalid candidate IDs')
        inputs = [x for x in inputs if x['item_id'] in set(ids)]
    out = HERE / 'runs' / args.run_id
    meta = {
        'phase': args.phase,
        'repeat_number': args.repeat_number,
        'config': cfg,
        'git_commit': commit,
        'python': platform.python_version(),
        'platform': platform.platform(),
        'dependencies': environment_versions(),
        'source_files': files,
        'item_ids': [x['item_id'] for x in inputs],
        'input_content_sha256': digest(canonical([(x['item_id'], digest(canonical(build_body(x['question'], root, cfg)))) for x in inputs])),
    }
    path = out / 'metadata.json'
    if path.exists():
        if read_json(path) != meta:
            raise ValueError('Run identity changed. Do not resume with changed config, code or dataset.')
    else:
        write_json(path, meta)
    client = make_client(cfg)
    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg['concurrency']) as pool:
        futures = [
            pool.submit(call_one, x, root, cfg, out, client, args.retry_technical_errors)
            for x in inputs
        ]
        for i, f in enumerate(concurrent.futures.as_completed(futures), 1):
            print(i, len(inputs), f.result(), flush=True)


def score(root: Path, cfg: dict, run_id: str) -> None:
    out = HERE / 'runs' / run_id
    meta = read_json(out / 'metadata.json')
    _, keys, files = load_pool(root, meta['config']['categories'])
    if files != meta['source_files']:
        raise ValueError('Source files changed since run')
    rows = []
    for item_id in meta['item_ids']:
        path = out / 'raw' / (item_id + '.json')
        answer = None
        status = 'missing'
        official = None
        parser_error = None
        completed = False
        http200_finished = False
        served_model = ''
        response_status = ''
        incomplete_reason = ''
        input_tokens = ''
        output_tokens = ''
        reasoning_tokens = ''
        if path.exists():
            r = read_json(path)
            status = 'request_error'
            if r.get('http_status') == 200:
                try:
                    response = json.loads(r['response_text'])
                    served_model = response.get('model') or ''
                    response_status = response.get('status') or ''
                    incomplete_reason = (response.get('incomplete_details') or {}).get('reason') or ''
                    usage = response.get('usage') or {}
                    input_tokens = usage.get('input_tokens', '')
                    output_tokens = usage.get('output_tokens', '')
                    reasoning_tokens = (usage.get('output_tokens_details') or {}).get('reasoning_tokens', '')
                    if response_status == 'completed':
                        completed = True
                        http200_finished = True
                        text = output_text(response)
                        answer, status = parse_answer(text)
                        official, parser_error = upstream_prediction(text)
                    elif response_status == 'incomplete':
                        http200_finished = True
                        status = f'incomplete_{incomplete_reason}' if incomplete_reason else 'incomplete_response'
                        text = output_text(response)
                        official, parser_error = upstream_prediction(text)
                    else:
                        status = 'incomplete_response'
                except (json.JSONDecodeError, TypeError):
                    status = 'malformed_response'
        rows.append({
            'item_id': item_id,
            'category': item_id.rsplit('-', 1)[0],
            'parsed_answer': answer,
            'gold_answer': keys[item_id],
            'status': status,
            'strict_correct': int(answer == keys[item_id]) if status == 'valid' else '',
            'completed': completed,
            'http200_finished': http200_finished,
            'served_model': served_model,
            'response_status': response_status,
            'incomplete_reason': incomplete_reason,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'reasoning_tokens': reasoning_tokens,
            'upstream_prediction': official,
            'upstream_parser_error': parser_error or '',
            'upstream_correct': int(official == keys[item_id]) if http200_finished and not parser_error else '',
        })
    with (out / 'scores.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {}
    for cat in meta['config']['categories']:
        rr = [r for r in rows if r['category'] == cat]
        valid = [r for r in rr if r['status'] == 'valid']
        ncorrect = sum(r['strict_correct'] for r in valid)
        done = [r for r in rr if r['completed']]
        finished = [r for r in rr if r['http200_finished']]
        incomplete = [r for r in rr if r['response_status'] == 'incomplete']
        official_correct = sum(r['upstream_correct'] for r in finished if r['upstream_correct'] != '')
        comparable = len(finished) == len(rr) and not any(r['upstream_parser_error'] for r in rr)
        strict_completed_gate = len(done) == len(rr) and not any(r['upstream_parser_error'] for r in rr)
        models = sorted({r['served_model'] for r in rr if r['served_model']})
        out_toks = [r['output_tokens'] for r in rr if isinstance(r['output_tokens'], int)]
        reas_toks = [r['reasoning_tokens'] for r in rr if isinstance(r['reasoning_tokens'], int)]
        summary[cat] = {
            'n_expected': len(rr),
            'n_http200_finished': len(finished),
            'n_completed': len(done),
            'n_incomplete': len(incomplete),
            'n_valid': len(valid),
            'n_correct': ncorrect,
            'upstream_accuracy_full_pool': official_correct / len(rr) if comparable and rr else None,
            'upstream_accuracy_completed_only_gate': official_correct / len(rr) if strict_completed_gate and rr else None,
            'upstream_correct_over_expected_lower_bound': official_correct / len(rr) if rr else None,
            'upstream_full_pool_reportable': comparable,
            'accuracy_valid_only': ncorrect / len(valid) if valid else None,
            'correct_over_all_expected': ncorrect / len(rr) if rr else None,
            'served_models': models,
            'single_served_model': len(models) == 1,
            'max_output_tokens_observed': max(out_toks) if out_toks else None,
            'max_reasoning_tokens_observed': max(reas_toks) if reas_toks else None,
            'status_counts': {s: sum(r['status'] == s for r in rr) for s in sorted(set(r['status'] for r in rr))},
        }
    write_json(out / 'summary.json', summary)
    print('Scores saved. Check missing/error/invalid counts before claiming full-pool accuracy.')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=['audit', 'run', 'score', 'select-candidates', 'check-stability'])
    ap.add_argument('--data-root', type=Path)
    ap.add_argument('--config', type=Path, default=HERE / 'config.json')
    ap.add_argument('--run-id', default='technical-001')
    ap.add_argument('--phase', choices=['technical', 'full', 'repeat'], default='technical')
    ap.add_argument('--candidate-ids', type=Path)
    ap.add_argument('--repeat-number', type=int, default=1)
    ap.add_argument('--retry-technical-errors', action='store_true')
    ap.add_argument('--per-category', type=int, default=40)
    ap.add_argument('--seed', type=int, default=20261119)
    ap.add_argument('--repeat-run-ids', nargs='+')
    ap.add_argument('--min-agreement', type=int, default=4)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', args.run_id):
        ap.error('run-id must contain only letters, numbers, underscores or hyphens')
    cfg = read_json(args.config)
    if args.command in ('audit', 'run', 'score') and args.data_root is None:
        ap.error(f'{args.command} requires --data-root')
    if args.command == 'audit':
        audit(args.data_root, cfg)
    elif args.command == 'run':
        run(args.data_root, cfg, args)
    elif args.command == 'score':
        score(args.data_root, cfg, args.run_id)
    elif args.command == 'select-candidates':
        out_path = args.out or (HERE / 'local' / 'candidate_ids.json')
        res = select_pilot_candidates(
            HERE / 'runs' / args.run_id / 'scores.csv',
            HERE / 'manifests' / 'items.csv',
            args.per_category,
            args.seed,
            out_path,
            data_root=args.data_root,
        )
        print(json.dumps(res))
    elif args.command == 'check-stability':
        if not args.repeat_run_ids or not args.candidate_ids:
            ap.error('check-stability requires --repeat-run-ids (4 IDs) and --candidate-ids')
        out_path = args.out or (HERE / 'runs' / 'stability_summary.json')
        res = evaluate_stability(
            HERE / 'runs',
            args.run_id,
            args.repeat_run_ids,
            args.candidate_ids,
            args.min_agreement,
            out_path,
        )
        print(json.dumps({'total_candidates': res['total_candidates'], 'total_stable': res['total_stable']}))


if __name__ == '__main__':
    main()
