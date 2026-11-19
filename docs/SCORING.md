# Scoring and parsing

Version: `space-primary-strict-secondary-v2`.

Primary benchmark scoring reuses `parse_answer_from_response` from upstream `QA_Agent` (with only the unused `self` parameter removed). It extracts the last brace-delimited substring, decodes JSON, reads `answer` or a single-key fallback, casts integer-like values with `int()`, and evaluates `prediction == gold`.

All finished HTTP 200 responses (`status == "completed"` and `status == "incomplete"`, such as `max_output_tokens` exhaustion) enter the primary full-pool denominator, matching upstream `evaluate_qas.py` where truncated or unparseable generations count as incorrect. `summary.json` also reports `upstream_accuracy_completed_only_gate`, `n_incomplete`, `max_output_tokens_observed`, `max_reasoning_tokens_observed`, and `served_models` (confirming whether a single backend snapshot served every item). If the upstream parser raises an exception or any item lacks an HTTP 200 response, `upstream_accuracy_full_pool` is set to `null`.

Secondary strict scoring (`parse_answer`) requires every JSON object containing `answer` in `output_text` to agree on a single integer in `{1, 2, 3, 4}`. It rejects string numerals, booleans, out-of-range integers, conflicting JSON blocks, and truncated (`incomplete`) responses. Only items with `status == "valid"` under the strict parser are eligible for human advice presentation in `select-candidates` and `check-stability`.

Transient HTTP 429, 5xx, and connection drops are handled by the `OpenAI` SDK according to `max_retries`. Persistent technical failures logged to `raw/` are preserved on standard resume; passing `--retry-technical-errors` moves non-200 or interrupted records into `failed_attempts/` before retrying them. Completed HTTP 200 responses are never retried or replaced.
