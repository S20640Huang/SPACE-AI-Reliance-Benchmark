"""Audited transport-only recovery of existing repeat-run timeouts.

Dry run by default. Preserve original metadata and all HTTP 200 responses.
"""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import benchmark as b


def recoverable_failure(record: dict) -> bool:
    if record.get('http_status') is None:
        return record.get('transport_error') in ('APITimeoutError', 'APIConnectionError')
    if record.get('http_status') == 429:
        try:
            error = json.loads(record.get('response_text', '{}')).get('error', {})
            return error.get('code') == 'credit_balance_exhausted'
        except (ValueError, AttributeError, TypeError):
            return False
    return False


def recovery_record(out: Path, item_id: str) -> dict:
    """Use prior timeout provenance only for an explicitly journalled interruption."""
    raw = out / 'raw' / f'{item_id}.json'
    if raw.exists():
        return b.read_json(raw)
    request = out / 'requests' / f'{item_id}.json'
    if request.exists():
        request_hash = b.digest(b.canonical(b.read_json(request)))
        for journal_path in sorted((out / 'recovery').glob('*/recovery.json'), reverse=True):
            journal = b.read_json(journal_path)
            backup = journal_path.parent / 'raw' / f'{item_id}.json'
            saved_request = journal_path.parent / 'requests' / f'{item_id}.json'
            if item_id not in journal.get('items', []) or not backup.exists() or not saved_request.exists():
                continue
            if any(x.get('item_id') == item_id for x in journal.get('results', [])):
                raise ValueError(f'{item_id}: journal reports a result but raw record is missing.')
            record = b.read_json(backup)
            if (recoverable_failure(record)
                    and record.get('request_sha256') == request_hash
                    and b.digest(b.canonical(b.read_json(saved_request))) == request_hash):
                return record
    raise ValueError(f'{item_id}: missing record without verified interrupted-recovery provenance.')


def select_timeouts(out: Path, ids: list[str]) -> list[str]:
    selected = []
    for item_id in ids:
        record = recovery_record(out, item_id)
        if record.get('http_status') == 200:
            continue  # Never retry completed, incomplete or invalid HTTP 200 responses.
        if recoverable_failure(record):
            selected.append(item_id)
        else:
            raise ValueError(f'{item_id}: unexpected failure type; inspect before recovery.')
    return selected


def verify_body(item: dict, root: Path, cfg: dict, out: Path) -> str:
    item_id = item['item_id']
    body_hash = b.digest(b.canonical(b.build_body(item['question'], root, cfg)))
    saved_hash = b.digest(b.canonical(b.read_json(out / 'requests' / f'{item_id}.json')))
    if body_hash != saved_hash or body_hash != recovery_record(out, item_id)['request_sha256']:
        raise ValueError(f'{item_id}: request changed; refusing recovery.')
    return body_hash


def prepare(root: Path, run_ids: list[str]) -> list[dict]:
    cfg = b.read_json(b.HERE / 'config.json')
    frozen = b.read_json(b.HERE / 'local' / 'candidate_ids.json')
    jobs = []
    for run_id in run_ids:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
            raise ValueError('Invalid run ID')
        out = b.HERE / 'runs' / run_id
        meta = b.read_json(out / 'metadata.json')
        if meta['phase'] != 'repeat' or meta['repeat_number'] not in (2, 3, 4, 5):
            raise ValueError('Only existing candidate repeat runs can be recovered.')
        if cfg != meta['config']:
            raise ValueError('config.json changed; restore the original config before recovery.')
        if meta['dependencies'] != b.environment_versions():
            raise ValueError('Dependency versions changed since the original run.')
        if meta['python'] != b.platform.python_version():
            raise ValueError('Python version changed since the original run.')
        if len(frozen) != len(set(frozen)) or len(meta['item_ids']) != len(frozen) or set(meta['item_ids']) != set(frozen):
            raise ValueError('Frozen candidate IDs changed.')
        # New recovery code gets its own commit; original runner and scoring code must match.
        for name in ('benchmark.py', 'space_adapter.py', 'selection.py',
                     'vendor/space_functions.py', 'vendor/__init__.py', 'config.json'):
            old = subprocess.run(['git', 'show', f'{meta["git_commit"]}:{name}'],
                                 cwd=b.HERE, capture_output=True, check=True).stdout
            if old != (b.HERE / name).read_bytes():
                raise ValueError(f'{name} changed since {run_id}.')
        pool, _, files = b.load_pool(root, cfg['categories'])
        if files != meta['source_files']:
            raise ValueError('Source question files changed.')
        by_id = {x['item_id']: x for x in pool}
        hashes = [(i, b.digest(b.canonical(b.build_body(by_id[i]['question'], root, cfg)))) for i in meta['item_ids']]
        if b.digest(b.canonical(hashes)) != meta['input_content_sha256']:
            raise ValueError('Input content changed.')
        selected = select_timeouts(out, meta['item_ids'])
        for i in selected:
            verify_body(by_id[i], root, cfg, out)
        jobs.append({'run_id': run_id, 'out': out, 'meta': meta, 'cfg': cfg,
                     'items': [by_id[i] for i in selected]})
    return jobs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-root', required=True, type=Path)
    ap.add_argument('--run-ids', nargs='+', default=['candidates-r4', 'candidates-r5'])
    ap.add_argument('--timeout-seconds', type=int, default=600)
    ap.add_argument('--execute', action='store_true', help='Send paid API requests; default is offline inspection.')
    args = ap.parse_args()
    if args.timeout_seconds <= 180:
        ap.error('Recovery timeout must exceed the original 180 seconds.')
    if len(args.run_ids) != len(set(args.run_ids)):
        ap.error('Duplicate run IDs')
    jobs = prepare(args.data_root, args.run_ids)
    print(json.dumps({'mode': 'execute' if args.execute else 'dry_run',
                      'timeout_seconds': args.timeout_seconds, 'concurrency': 1,
                      'retry_items': {j['run_id']: [x['item_id'] for x in j['items']] for j in jobs}}, indent=2), flush=True)
    if not args.execute:
        return
    if not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('Set OPENAI_API_KEY in your terminal. Never save it in the repository.')
    commit = b.git_commit()
    lock = b.HERE / 'local' / 'timeout_recovery.lock'
    lock.parent.mkdir(exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for job in jobs:
            if not job['items']:
                print(f'{job["run_id"]}: no timeouts to recover', flush=True)
                continue
            out = job['out']
            meta_hash = b.digest((out / 'metadata.json').read_bytes())
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            folder = out / 'recovery' / stamp
            folder.mkdir(parents=True)
            journal = {'reason': 'Transport failure or exhausted credits after replenishment; settings unchanged',
                       'original_git_commit': job['meta']['git_commit'], 'recovery_git_commit': commit,
                       'recovery_script_sha256': b.digest(Path(__file__).read_bytes()),
                       'original_metadata_sha256': meta_hash,
                       'original_timeout_seconds': job['cfg']['timeout_seconds'],
                       'effective_timeout_seconds': args.timeout_seconds, 'effective_concurrency': 1,
                       'max_retries': job['cfg']['max_retries'],
                       'items': [x['item_id'] for x in job['items']], 'results': []}
            b.write_json(folder / 'recovery.json', journal)
            transport_cfg = dict(job['cfg'], timeout_seconds=args.timeout_seconds)
            with b.make_client(transport_cfg) as client:
                for item in job['items']:
                    item_id = item['item_id']
                    # Recheck immediately before mutation; never replace a newly saved HTTP 200.
                    if not select_timeouts(out, [item_id]):
                        continue
                    verify_body(item, args.data_root, job['cfg'], out)
                    if not (out / 'raw' / f'{item_id}.json').exists():
                        journal.setdefault('interrupted_items', []).append(item_id)
                        b.write_json(folder / 'recovery.json', journal)
                    for sub in ('raw', 'requests'):
                        if not (out / sub / f'{item_id}.json').exists():
                            continue
                        dst = folder / sub / f'{item_id}.json'
                        dst.parent.mkdir(exist_ok=True)
                        shutil.copy2(out / sub / f'{item_id}.json', dst)
                    print(f'{job["run_id"]}: recovering {item_id}', flush=True)
                    b.call_one(item, args.data_root, job['cfg'], out, client=client, retry_technical_errors=True)
                    result = b.read_json(out / 'raw' / f'{item_id}.json')
                    journal['results'].append({'item_id': item_id, 'http_status': result.get('http_status'),
                                               'transport_error': result.get('transport_error'),
                                               'raw_sha256': b.digest((out / 'raw' / f'{item_id}.json').read_bytes())})
                    b.write_json(folder / 'recovery.json', journal)
                    print(f'{item_id}: HTTP {result.get("http_status")}, {result.get("transport_error", "response saved")}', flush=True)
            if b.digest((out / 'metadata.json').read_bytes()) != meta_hash:
                raise ValueError('Original metadata changed unexpectedly.')
            b.score(args.data_root, job['cfg'], job['run_id'])
    print('Recovery pass finished. Check summaries before calculating stability.', flush=True)


if __name__ == '__main__':
    main()
