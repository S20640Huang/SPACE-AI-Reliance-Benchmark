# Run plan

1. Run `audit` on the four local QA folders (`MRT_vision`, `PTT_vision`, `JLO_vision`, `MPFB_vision`) to verify all 1,488 records, source SHA-256 digests, 218 layout families (`layout_family_sha256`), and 518 option-content groups (`option_group_sha256`). JLO contributes 196 option-content groups across 50 layouts because distractor sets can differ.
2. Confirm `model_snapshot` (e.g., `gpt-5.4-2026-03-05`), `reasoning_effort` (`"medium"`), `max_output_tokens` (`16384` or `32768`), `image_detail` (`"low"`), and `max_retries` (`2`) in `config.json`, then commit and push before live calls.
3. Run `--phase technical --run-id technical-001` (first 2 records per category; 8 items) and `score`. Check `max_output_tokens_observed`, `max_reasoning_tokens_observed`, `n_incomplete`, `served_models`, and label legibility in `PTT_vision` and `JLO_vision`. Commit any parameter adjustment before `full-001`.
4. Run `--phase full --run-id full-001` across all 1,488 records and `score`. If transient network or rate-limit errors remain after SDK retries, rerun with `--retry-technical-errors` so failed attempts are archived in `failed_attempts/` and retried without touching completed HTTP 200 responses.
5. Report category accuracy (`upstream_accuracy_full_pool`), `n_incomplete`, `status_counts`, and `served_models`.
6. Run `select-candidates` (`--per-category 40` with a fixed seed). `MRT_vision` (98 layouts), `JLO_vision` (50 layouts), and `MPFB_vision` (50 layouts) deduplicate by `layout_family_sha256`; `PTT_vision` deduplicates by `option_group_sha256` (100 distinct perspective questions across 20 scenes) and balances selections round-robin across all 20 scenes. When a category has fewer than `per_category // 2` representatives in a stratum after initial uniform group draws (e.g., PTT's 9 distinct error questions), mixed groups containing a valid minority-stratum record are promoted up to `per_category // 2` while retaining at most one record per group, and any remaining shortfall is filled from the majority stratum. Freeze candidate IDs before repeats.
7. Run `--phase repeat` four times (`--repeat-number` 2, 3, 4, 5 as `candidates-r2` through `candidates-r5`) with identical scientific settings, scoring each run.
8. Run `check-stability` (`--min-agreement 4`) to retain candidates where run 1 produced a valid integer option in `{1, 2, 3, 4}` and at least 4 of 5 runs agree on correctness. Report both correctness agreement and exact-option agreement.
9. Conduct the independent human pilot on stable candidates after ethics approval, then partition distinct `layout_family_sha256` families across learning and retention sets to prevent stimulus leakage.

## Full-run readiness update (2026-11-20)

Technical-001 completed all 8 requests with valid answers and the expected model snapshot. Its maximum output usage was 8,620 tokens (8,605 reasoning), triggering the prespecified increase from 16,384 to 32,768 before full-001. All technical preview images were verified readable. Preserve technical-001 unchanged and use 32,768 for full-001 and candidate stability repeats.

## Transport recovery amendment (2026-11-22)

After repeated technical retries, four recorded APITimeoutError failures remained: candidates-r4 MPFB_vision-00124, MPFB_vision-00165 and MPFB_vision-00177; candidates-r5 MPFB_vision-00177. No response correctness was available for these failed attempts. One recovery pass uses a 600-second SDK timeout and sequential requests, retaining the SDK retry count of 2. The timeout is a client transport setting, not a model reasoning-token budget or a guarantee of total elapsed duration. Timed-out server work may still incur charges.

Use recover_timeouts.py, which defaults to an offline dry run. It verifies original runner code, config, source files, candidate IDs and request hashes. It only selects existing APITimeoutError records, preserves every HTTP 200 response, archives old raw responses and requests, and leaves the original metadata unchanged. Separate timestamped recovery journals record the amended transport settings, original and recovery commits, request outcome and file hashes. Do not change config.json or edit historical metadata to bypass resume checks. Do not run recovery concurrently with the original runner. Commit and publish this amendment before using --execute. If failures persist after this pass, inspect them before another recovery pass; do not substitute easier questions or retry completed answers.

Offline check:
`uv run --python 3.15 python recover_timeouts.py --data-root /path/to/SPACE_data_release`

Paid recovery (after all original runs have stopped):
`uv run --python 3.15 python recover_timeouts.py --data-root /path/to/SPACE_data_release --execute`

Interrupted recovery may resume when a missing raw response has a matching saved
request and a prior recovery journal with a backed-up timeout record and no
completed result for that item. Payload hashes must agree. This is recorded as an
interruption, not a newly observed timeout; the pending request is archived by the
original runner before resubmission. No HTTP 200 response is replaced. A request
interrupted locally may already have incurred server-side charges.
