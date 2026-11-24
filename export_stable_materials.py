"""Copy stable SPACE stimuli into task folders without modifying the dataset.

Standard-library only. Output is a researcher materials archive, not a ready-to-
import Gorilla spreadsheet. Original text (including API instructions) is kept.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
CATEGORIES = ('MRT_vision', 'MPFB_vision', 'JLO_vision', 'PTT_vision')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def export_materials(data_root, stability_path, manifest_path, output):
    data_root = data_root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError(f'Output already exists: {output}. Use a new --output directory; existing files are never overwritten.')
    if output == data_root or data_root in output.parents:
        raise ValueError('Choose an output directory outside the original dataset.')
    summary = read_json(stability_path)
    ids = summary['stable_item_ids']
    if not ids or len(ids) != len(set(ids)) or len(ids) != summary['total_stable']:
        raise ValueError('Stable ID list is empty, duplicated, or inconsistent with total_stable.')
    with manifest_path.open(encoding='utf-8', newline='') as handle:
        manifest = {r['item_id']: r for r in csv.DictReader(handle)}
    pools = {cat: read_json(data_root / cat / 'qas.json') for cat in CATEGORIES}
    records, copies = [], {}
    for item_id in ids:
        match = re.fullmatch(r'(MRT_vision|MPFB_vision|JLO_vision|PTT_vision)-(\d{5})', item_id)
        if not match:
            raise ValueError(f'Unexpected item ID: {item_id}')
        cat, index = match.group(1), int(match.group(2))
        rec = pools[cat][index]
        question = rec['question']
        if not isinstance(question, list) or not all(isinstance(x, str) for x in question):
            raise ValueError(f'{item_id}: invalid question format')
        segments, images = [], []
        for position, segment in enumerate(question):
            if not segment.startswith('IMAGE:'):
                segments.append({'type': 'text', 'text': segment})
                continue
            original = segment[len('IMAGE:'):]
            parts = PurePosixPath(original).parts
            if '..' in parts or parts[:2] != ('data', 'SPACE_data_release'):
                raise ValueError(f'{item_id}: unexpected image path {original}')
            relative = PurePosixPath(*parts[2:])
            if relative.parts[:2] != (cat, 'images'):
                raise ValueError(f'{item_id}: image outside task image directory')
            source = (data_root / relative).resolve()
            if data_root not in source.parents or not source.is_file():
                raise ValueError(f'{item_id}: missing or unsafe image path {original}')
            digest = sha256(source)
            copies[str(relative)] = (source, digest)
            image = {'question_segment_index': position, 'source_reference': original,
                     'export_path': str(relative), 'sha256': digest}
            images.append(image)
            segments.append({'type': 'image', 'path': str(relative)})
        if not images:
            raise ValueError(f'{item_id}: no images')
        # Detect a changed source dataset before associating it with scored IDs.
        expected = manifest[item_id]['image_sha256'].split(';')
        if [x['sha256'] for x in images] != expected:
            raise ValueError(f'{item_id}: image hashes differ from the benchmark manifest')
        question_hash = hashlib.sha256(json.dumps(question, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if question_hash != manifest[item_id]['question_sha256']:
            raise ValueError(f'{item_id}: question differs from the benchmark manifest')
        records.append({'item_id': item_id, 'category': cat, 'source_record_index': index,
                        'layout_family_sha256': manifest[item_id]['layout_family_sha256'],
                        'option_group_sha256': manifest[item_id]['option_group_sha256'],
                        'original_question': question, 'ordered_segments': segments,
                        'images': images, 'gold_answer_researcher_only': rec['answer']})
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.space-export-', dir=output.parent))
    try:
        for relative, (source, digest) in copies.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha256(destination) != digest:
                raise ValueError(f'Copy verification failed: {relative}')
        for cat in CATEGORIES:
            (staging / cat).mkdir(exist_ok=True)
            write_json(staging / cat / 'items.json', [r for r in records if r['category'] == cat])
        write_json(staging / 'item_image_mapping.json', records)
        report = {'stable_items': len(records), 'unique_image_files': len(copies),
                  'image_references': sum(len(r['images']) for r in records),
                  'stability_file_sha256': sha256(stability_path),
                  'manifest_sha256': sha256(manifest_path),
                  'export_script_sha256': sha256(Path(__file__)),
                  'categories': {cat: {'items': sum(r['category'] == cat for r in records),
                      'unique_images': sum(p.startswith(cat + '/') for p in copies)} for cat in CATEGORIES}}
        write_json(staging / 'export_summary.json', report)
        (staging / 'README.txt').write_text(
            'SPACE stable candidate materials — researcher archive\n\n'
            'Images are unchanged copies of source PNGs, grouped by task. Shared images\n'
            'are copied once; each question retains its own ordered image references.\n'
            'items.json and item_image_mapping.json contain the original question text,\n'
            'option order, layout identifiers, and researcher-only correct answers.\n'
            'Do not display the correct-answer fields to participants. Original API\n'
            'JSON-output instructions are preserved for provenance; adapt response\n'
            'instructions separately for humans and document that adaptation.\n\n'
            'This is NOT a ready-to-import Gorilla task spreadsheet. It is also NOT\n'
            'the exact API image payload: the benchmark used JPEG conversion and low\n'
            'image detail. Verify the chosen human presentation before piloting.\n'
            'Preserve layout-based allocation; this archive is not one participant list.\n'
            'Keep this archive local unless stimulus redistribution is licensed.\n', encoding='utf-8')
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--stability', type=Path, default=HERE / 'runs/stability_summary.json')
    parser.add_argument('--manifest', type=Path, default=HERE / 'manifests/items.csv')
    parser.add_argument('--output', type=Path, default=HERE / 'local/gorilla_pilot_materials')
    args = parser.parse_args()
    result = export_materials(args.data_root, args.stability, args.manifest, args.output)
    print(json.dumps(result, indent=2))
    print(f'Saved to: {args.output.resolve()}')


if __name__ == '__main__':
    main()
