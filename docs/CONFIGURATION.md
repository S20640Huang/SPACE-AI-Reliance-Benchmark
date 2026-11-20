# Configuration fields

The repository ships with `status` set to `"review_pending_model_and_parameters"` so live API calls remain blocked until final configuration sign-off.

- `model_snapshot`: `null` pending final selection (recommended dated snapshot: `gpt-5.4-2026-03-05`). By default `validate_live` requires a `YYYY-MM-DD` date in the identifier.
- `allow_undated_model_id`: `false` by default. Set `true` only if an undated model identifier (e.g., `gpt-6-astra` or `gpt-6.2-astra`) is explicitly approved; `score` still verifies whether `served_models` remained constant across all items.
- `reasoning_effort`: `null` pending final confirmation (recommended: `"medium"`). When `null`, the parameter is omitted.
- `max_output_tokens`: `null` pending confirmation (recommended: `16384` or `32768`, since `max_output_tokens` caps internal reasoning tokens plus visible output text in the `Responses` API).
- `image_detail`: `"low"` to match upstream SPACE `gpt4o_qa` and `gpt4v_qa` configurations. Verify label legibility in `PTT_vision` and `JLO_vision` during the technical run.
- `concurrency`: `3` concurrent independent requests sharing one `OpenAI` client instance. Run one process per `run_id`.
- `timeout_seconds`: `180` seconds per HTTP request.
- `max_retries`: `2` SDK retries for transient transport, HTTP 429, and HTTP 5xx errors using `OpenAI` idempotency keys. Set `0` to disable automatic SDK retries.
- `upstream_commit`: `"eec58a24516bfcd4554807b0a2b9d08b04eafd1c"`, verified by exact SHA-256 match across all six inspected files in `apple-aiml-research/ml-space-benchmark`.
- `upstream_implementation_checked`: `true` following offline parity verification across all 1,488 records and 5,240 image occurrences.
- `model_settings_verified`: `false` until the live `technical` check confirms endpoint, token budget, and image legibility.
- `failure_policy_approved`: `false` until retry settings are confirmed.
- `status`: set to `"ready"` only after completing pre-run checks.
- `protocol_version` / `parser_version`: `"review-3"` / `"space-primary-strict-secondary-v2"`.

`temperature`, `top_p`, `seed`, `tools`, `previous_response_id`, and custom system prompts are omitted. `store=false` is sent on every request. `OPENAI_API_KEY` is read exclusively from the environment.
