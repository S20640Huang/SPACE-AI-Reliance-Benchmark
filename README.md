# SPACE AI reliability benchmarking

**Review version 3: verified offline on Python 3.15; live execution remains gated pending final model and parameter confirmation.**

The harness adapts the SPACE visual QA loader, reuses the original JPEG encoder and primary answer parser, sends independent requests through the official OpenAI Python SDK (`Responses` API), archives raw requests and responses locally, and implements stimulus-family deduplication, stratified pilot candidate selection, and five-run stability filtering. Original Apple licensing notices are retained in `vendor/`.

## Scope and methods

The four local QA files contain 688 `MRT_vision`, 400 `PTT_vision`, 200 `JLO_vision`, and 200 `MPFB_vision` records (1,488 total across 372 four-way answer-order permutation groups and 218 base image layouts). Category labels come from the folder names because all source `task` fields are labelled `MRT (vision)`. All 1,488 records are retained for the full-pool pass. Item IDs use zero-based row indices pinned by source SHA-256 digests.

Each request sends one original question with its ordered text and image segments. Gold labels, task metadata, examples, and prior turns never enter the request builder. Images are decoded to RGB with Pillow and encoded to JPEG with the extracted upstream encoder (`image_detail="low"` by default).

Primary scoring applies the extracted upstream `parse_answer_from_response` function and evaluates `prediction == gold` over all completed and token-exhausted HTTP 200 responses. A secondary strict parser requires a single unambiguous integer option in `{1, 2, 3, 4}` for diagnostics and participant advice eligibility. See `docs/SCORING.md`.

## Files

- `benchmark.py`: dataset audit, OpenAI SDK execution, safe resume/error recovery, scoring, and CLI entrypoints.
- `selection.py`: option-permutation normalization, stratified pilot candidate preselection, and five-run stability filtering.
- `space_adapter.py`: adapted upstream question-segment loader and validated local image path resolution.
- `vendor/space_functions.py`: extracted upstream JPEG encoder and answer parser with Apple notices.
- `config.json`: pinned upstream commit (`eec58a24516bfcd4554807b0a2b9d08b04eafd1c`) and gated model settings.
- `pyproject.toml`, `.python-version`, `requirements.txt`: Python 3.15 environment and pinned dependencies (`Pillow`, `numpy`, `openai`).
- `docs/`: configuration, prompting, scoring, execution, and upstream reconciliation specifications.
- `manifests/`: item hash inventory without stimulus text or answer keys.
- `tests/` and `audit/`: offline unit tests and upstream parity verification tools.

## Installation and offline checks

Use Python 3.15 in an isolated virtual environment (`uv` or `venv`). From the repository root:

```sh
uv sync --python 3.15
uv run --python 3.15 python -m unittest discover -s tests -v
uv run --python 3.15 python benchmark.py audit --data-root /path/to/SPACE_data_release
uv run --python 3.15 python audit/verify_parity.py /path/to/ml-space-benchmark /path/to/SPACE_data_release
```

Standard `venv` installation is also supported on Python 3.15 via `python -m pip install -r requirements.txt`. None of these commands makes network calls. `audit` writes a local-only request preview to `local/request_preview.json`, which is excluded by `.gitignore`.

## Model configuration and live execution

Before live execution, set the agreed `model_snapshot`, `reasoning_effort`, and `max_output_tokens` in `config.json`, verify parameters and failure policy, set `status` to `"ready"`, commit and push a clean Git working tree, and export `OPENAI_API_KEY` in the shell environment.

```sh
# 1. Technical check (first 2 records per category; 8 requests total):
uv run --python 3.15 python benchmark.py run --data-root /path/to/SPACE_data_release --phase technical --run-id technical-001
uv run --python 3.15 python benchmark.py score --data-root /path/to/SPACE_data_release --run-id technical-001

# 2. Freeze final config commit, then run the full 1,488-record pool:
uv run --python 3.15 python benchmark.py run --data-root /path/to/SPACE_data_release --phase full --run-id full-001
uv run --python 3.15 python benchmark.py score --data-root /path/to/SPACE_data_release --run-id full-001

# 3. Preselect stratified pilot candidates (1 variant per permutation group):
uv run --python 3.15 python benchmark.py select-candidates --run-id full-001 --data-root /path/to/SPACE_data_release --per-category 40 --seed 20261119 --out local/candidate_ids.json

# 4. Run 4 stability repeats on frozen candidate IDs and filter (>= 4 of 5 correctness agreement):
uv run --python 3.15 python benchmark.py run --data-root /path/to/SPACE_data_release --phase repeat --candidate-ids local/candidate_ids.json --repeat-number 2 --run-id candidates-r2
uv run --python 3.15 python benchmark.py score --data-root /path/to/SPACE_data_release --run-id candidates-r2
# (repeat for numbers 3, 4, 5 as candidates-r3, candidates-r4, candidates-r5)
uv run --python 3.15 python benchmark.py check-stability --run-id full-001 --repeat-run-ids candidates-r2 candidates-r3 candidates-r4 candidates-r5 --candidate-ids local/candidate_ids.json --min-agreement 4 --out runs/stability_summary.json
```

The runner reuses one thread-safe `OpenAI` client across concurrent workers (`max_retries` handles transient HTTP 429, 5xx, and transport drops with idempotency headers). Re-running the identical command resumes remaining items without resubmitting logged responses. Passing `--retry-technical-errors` archives non-200 or interrupted prior attempts under `runs/<run_id>/failed_attempts/` before retrying them; HTTP 200 responses are never overwritten or resampled.

## Publication and licensing

Commit and push the frozen repository state before starting `full-001`. `.gitignore` excludes `data/`, `local/`, and `runs/` so SPACE stimuli (CC BY-NC-ND 4.0) and gold keys are kept out of version control. Always push via Git CLI so `.gitignore` rules apply.

SPACE source: https://github.com/apple-aiml-research/ml-space-benchmark (commit `eec58a24516bfcd4554807b0a2b9d08b04eafd1c`). Paper: Ramakrishnan, Wijmans, Krähenbühl, and Koltun (2025), *Does Spatial Cognition Emerge in Frontier Models?*, ICLR.
