"""Execute selected upstream functions with fake model/client; no package imports or API.
Only use on trusted, manually inspected source. Source files remain unchanged.
"""
import ast
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import benchmark  # noqa: E402


def selected(path: Path, names: set[str], namespace: dict) -> None:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    for n in nodes:
        n.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)


def run(source: Path, data: Path) -> None:
    captures = []

    class Writer:
        def __init__(self):
            self.entries = []

        def write(self, text):
            self.entries.append(text)

    class Dialog:
        def __init__(self):
            self.history = []
            self.log_writer = Writer()

        @property
        def dialog(self):
            return copy.deepcopy(self.history)

        def add_user_message(self, **kw):
            self.history.append({'role': 'user', **kw})

        def add_assistant_message(self, **kw):
            self.history.append({'role': 'assistant', **kw})

        def delete_last_message(self):
            self.history.pop()

        def log_token_usage(self, *a):
            pass

        def log_response_time(self, *a):
            pass

    def fake_response(client, dialog, model_name, **kwargs):
        captures.append({'model': model_name, 'messages': copy.deepcopy(dialog), 'settings': kwargs})
        return {'text': '{"answer": 2}', 'completion_tokens': 1, 'prompt_tokens': 10, 'response_time': 0}

    ns = {
        'Any': Any,
        'Union': Union,
        'json': json,
        're': re,
        'count_images_in_query': lambda qc: sum(isinstance(x, dict) for x in qc),
        'get_model_response': fake_response,
    }
    selected(source / 'space/agents/qa_agent.py', {'is_int', 'QA_Agent'}, ns)
    cls = ns['QA_Agent']

    def fake_reset(self):
        self.dialog = Dialog()
        self.completion_tokens = 0
        self.prompt_tokens = 0

    cls.reset = fake_reset

    def fake_agent(name, cfg):
        agent = object.__new__(cls)
        defaults = {
            'model_name': 'gpt-4o-2024-05-13',
            'image_detail': 'low',
            'subsampling_factor': 1,
            'max_images_per_query': -1,
            'max_new_tokens': 4096,
            'completion_cost_per_mil': 0,
            'prompt_cost_per_mil': 0,
            'client': None,
        }
        for k, v in defaults.items():
            setattr(agent, k, v)
        return agent

    def fake_image(image_path, model_name, image_detail):
        return {'type': 'image_url', 'image_url': {'url': 'LOCAL_FILE:' + image_path, 'detail': image_detail}}

    ens = {'Any': Any, 'get_agent': fake_agent, 'get_image_as_message': fake_image}
    selected(source / 'space/evaluate_qas.py', {'evaluate_on_qa'}, ens)
    rows = []
    for cat in ['MRT_vision', 'PTT_vision', 'JLO_vision', 'MPFB_vision']:
        qas = json.loads((data / cat / 'qas.json').read_text(encoding='utf-8'))
        for i in range(2):
            qa = copy.deepcopy(qas[i])
            before = len(captures)
            _, pred, _ = ens['evaluate_on_qa']('QA_Agent', {}, qa)
            qa['answer'] = qa['answer'] % 4 + 1
            ens['evaluate_on_qa']('QA_Agent', {}, qa)
            assert captures[before] == captures[before + 1]
            assert len(captures[before]['messages']) == 1
            rows.append({
                'item_id': f'{cat}-{i:05d}',
                'changed_gold_did_not_change_model_messages': True,
                'fresh_single_user_message': True,
                'fake_prediction': pred,
            })
    parser = object.__new__(cls)
    comparisons = []
    for text in ['{"answer": 2}', '{"answer": "2"}', '{"choice": 2}', '{"answer":1}\n{"answer":2}', '{"answer":true}', '2']:
        comparisons.append({
            'response': text,
            'upstream': parser.parse_answer_from_response(text),
            'draft': benchmark.parse_answer(text)[0],
        })
    paths = [
        'space/evaluate_qas.py',
        'space/agents/qa_agent.py',
        'space/utils/common.py',
        'space/utils/openai_api.py',
        'space/utils/model.py',
        'space/configs/gpt.py',
    ]
    report = {
        'date': '2026-11-19',
        'upstream_commit': 'eec58a24516bfcd4554807b0a2b9d08b04eafd1c',
        'source_has_git_directory': (source / '.git').is_dir(),
        'source_sha256': {p: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in paths},
        'tested_items': rows,
        'fake_model_calls': len(captures),
        'real_api_calls': 0,
        'parser_comparison': comparisons,
        'comparison_note': 'draft column is the strict secondary parser; current primary uses the extracted official parser',
        'limits': 'Selected original AST functions executed with fake client, dialog and image objects. Confirms control/data flow for these cases, not actual SDK/API or image encoding compatibility. No formal benchmark data collected.',
    }
    out = ROOT / 'audit' / 'upstream_offline_results.json'
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'items_checked': len(rows), 'gold_mutation_checks_passed': len(rows), 'real_api_calls': 0, 'report': str(out)}))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python audit/check_upstream_offline.py SOURCE_ROOT DATA_ROOT')
    run(Path(sys.argv[1]), Path(sys.argv[2]))
