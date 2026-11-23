"""Make one browsable folder per stable question from the verified material export."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
STYLE = '''body{font:18px/1.65 system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 24px;color:#222;background:#fafafa}img{max-width:100%;height:auto;background:white;border:1px solid #ddd}figure{margin:24px 0}figcaption,small{color:#666;font-size:14px}p{white-space:pre-wrap}a{color:#1459a0}li{margin:8px 0}header{border-bottom:1px solid #ddd;margin-bottom:24px}'''


def page(title, content):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title><style>' + STYLE + '</style><body>' + content + '</body></html>'


def build(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('Output already exists; choose a new --output folder.')
    records = json.loads((source / 'item_image_mapping.json').read_text(encoding='utf-8'))
    if len({r['item_id'] for r in records}) != len(records):
        raise ValueError('Duplicate question IDs')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.question-folders-', dir=destination.parent))
    index = ['<header><h1>SPACE · 稳定题目浏览</h1><p>每道题一个文件夹。点击编号查看题干、图片和选项。</p></header>',
             '<p>此页面用于研究者检查材料，不是正式 Gorilla 实验。正确答案保存在各题的 RESEARCHER_ONLY.json；题目预览不显示答案。原始 AI 输出格式指令单独保存，未放入预览。</p>']
    counts = Counter()
    try:
        for cat in ('MRT_vision', 'MPFB_vision', 'JLO_vision', 'PTT_vision'):
            group = [r for r in records if r['category'] == cat]
            index.append(f'<h2>{cat} · {len(group)} 题</h2><ul>')
            for r in group:
                item = r['item_id']
                folder = staging / cat / item
                folder.mkdir(parents=True)
                content = [f'<header><a href="../../index.html">← 返回题目目录</a><h1>{item}</h1></header>']
                plain = [item, '']
                image_index = 0
                instructions, image_map = [], []
                for seg in r['ordered_segments']:
                    if seg['type'] == 'text':
                        text = seg['text']
                        if text.startswith('Think step by step. Then answer your question in the following json format.'):
                            instructions.append(text)
                            continue
                        # SPACE contains literal backslash-n sequences in some text fields.
                        display = text.replace('\\n', '\n')
                        plain.append(display)
                        content.append('<p>' + html.escape(display) + '</p>')
                    else:
                        image_index += 1
                        if cat in ('MRT_vision', 'MPFB_vision'):
                            role = 'question' if image_index == 1 else f'option_{image_index-1}'
                        elif cat == 'JLO_vision':
                            role = 'question' if image_index == 1 else 'reference'
                        else:
                            role = 'scene'
                        src = (source / seg['path']).resolve()
                        if source not in src.parents:
                            raise ValueError('Image path outside source folder')
                        name = f'{image_index:02d}_{role}{src.suffix}'
                        shutil.copy2(src, folder / name)
                        original = r['images'][image_index-1]
                        digest = hashlib.sha256((folder / name).read_bytes()).hexdigest()
                        if digest != original['sha256']:
                            raise ValueError(f'{item}: image hash mismatch')
                        image_map.append(dict(original, local_filename=name))
                        plain.append(f'[图片：{name}]')
                        content.append(f'<figure><img src="{name}" alt="{role}"><figcaption>{name}</figcaption></figure>')
                if image_index != len(r['images']) or len(instructions) != 1:
                    raise ValueError(f'{item}: unexpected image or API instruction structure')
                (folder / 'question.txt').write_text('\n\n'.join(plain) + '\n', encoding='utf-8')
                (folder / 'preview.html').write_text(page(item, ''.join(content)), encoding='utf-8')
                (folder / 'original_api_instruction.txt').write_text('\n'.join(instructions), encoding='utf-8')
                metadata = dict(r, images=image_map,
                    presentation_note='Original wording and option order preserved; literal backslash-n displayed as line breaks; final AI JSON-output instruction omitted from preview only.')
                (folder / 'RESEARCHER_ONLY.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                index.append(f'<li><a href="{cat}/{item}/preview.html">{item}</a></li>')
                counts[cat] += 1
            index.append('</ul>')
        (staging / 'index.html').write_text(page('SPACE stable questions', ''.join(index)), encoding='utf-8')
        (staging / 'README.txt').write_text('Open index.html to browse all questions.\nEach question folder contains question.txt, preview.html and numbered image files.\nMRT/MPFB: 01_question, 02_option_1 through 05_option_4.\nJLO: 01_question and 02_reference. PTT: 01_scene.\nRESEARCHER_ONLY.json contains the gold answer and original source metadata; never show it to participants.\nOriginal AI JSON-output instructions are saved separately, not shown in preview.\nShared source images are copied into each relevant question folder for convenience.\nThese are original PNGs, not the benchmark JPEG/low-detail API rendering.\nThis is a materials browser, not a Gorilla import or participant assignment list.\n', encoding='utf-8')
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return dict(counts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE / 'local/gorilla_pilot_materials')
    parser.add_argument('--output', type=Path, default=HERE / 'local/gorilla_questions_by_item')
    args = parser.parse_args()
    print(build(args.source, args.output))
    print(args.output.resolve() / 'index.html')
