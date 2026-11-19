# Upstream reconciliation

Upstream repository: `https://github.com/apple-aiml-research/ml-space-benchmark` at commit `eec58a24516bfcd4554807b0a2b9d08b04eafd1c`. All six SHA-256 digests recorded in `audit/upstream_offline_results.json` match this commit byte-for-byte.

Upstream call chain: `evaluate_qas.py` -> `QA_Agent.get_prediction` -> `utils/model.py` -> `utils/openai_api.py` -> `chat.completions.create`. Each item runs in an isolated single-turn user message; the ground-truth `answer` is written only to the local transcript after model prediction.

## Reuse and adaptations

- `space_adapter.py` retains the segment-ordering control flow from `evaluate_qas.py`, adding explicit root containment checks, Pillow RGB decoding in place of `imageio.imread(..., pilmode="RGB")`, and rejection of video markers.
- `vendor/space_functions.py` extracts `encode_image`, `is_int`, and `parse_answer_from_response` with Apple copyright and license notices intact.
- `benchmark.py` uses the official `openai` Python SDK against the `Responses` API (`responses.with_raw_response.create`) on Python 3.15, translating string and `image_url` entries into `input_text` and `input_image` parts while preserving `image_detail="low"` and exact JPEG payloads.
- Upstream Chat Completions defaults (`temperature=0.5`, `max_tokens=4096`, `frequency_penalty=0.0`) are omitted because frontier reasoning models use `reasoning.effort` and count reasoning tokens inside `max_output_tokens`.
- `selection.py` adds deterministic option-permutation grouping (`option_group_sha256`), stratified candidate preselection (`select-candidates`), and five-run stability filtering (`check-stability`).

## Offline verification

- `audit/check_upstream_offline.py`: executes extracted upstream AST functions with mock client objects on the first two items per category and verifies that mutating gold labels leaves outbound payloads unchanged.
- `audit/verify_parity.py`: verifies exact text-order and JPEG base64 parity across all 1,488 records (5,240 image occurrences) and 15 parser edge cases.
- `tests/`: verifies Python 3.15 gates, `.gitignore` isolation of `local/`, `runs/`, and `data/`, OpenAI SDK raw logging and `--retry-technical-errors` archiving, `incomplete` token-limit scoring, permutation deduplication, and 4-of-5 stability filtering.
