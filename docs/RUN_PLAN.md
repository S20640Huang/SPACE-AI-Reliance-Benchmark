# Run plan

1. Run `audit` on the four local QA folders (`MRT_vision`, `PTT_vision`, `JLO_vision`, `MPFB_vision`) to verify all 1,488 records, source SHA-256 digests, 218 layout families (`layout_family_sha256`), and 372 four-way option-permutation groups (`option_group_sha256`).
2. Confirm `model_snapshot` (e.g., `gpt-5.4-2026-03-05`), `reasoning_effort` (`"medium"`), `max_output_tokens` (`16384` or `32768`), `image_detail` (`"low"`), and `max_retries` (`2`) in `config.json`, then commit and push before live calls.
3. Run `--phase technical --run-id technical-001` (first 2 records per category; 8 items) and `score`. Check `max_output_tokens_observed`, `max_reasoning_tokens_observed`, `n_incomplete`, `served_models`, and label legibility in `PTT_vision` and `JLO_vision`. Commit any parameter adjustment before `full-001`.
4. Run `--phase full --run-id full-001` across all 1,488 records and `score`. If transient network or rate-limit errors remain after SDK retries, rerun with `--retry-technical-errors` so failed attempts are archived in `failed_attempts/` and retried without touching completed HTTP 200 responses.
5. Report category accuracy (`upstream_accuracy_full_pool`), `n_incomplete`, `status_counts`, and `served_models`.
6. Run `select-candidates` on `full-001` with a fixed seed (e.g., `--per-category 40 --seed 20261119`) to sample at most one valid variant per option-permutation group, stratified by run-1 correctness. Commit the selection parameters and freeze the candidate ID list locally before repeats.
7. Run `--phase repeat` four times (`--repeat-number` 2, 3, 4, 5 as `candidates-r2` through `candidates-r5`) with identical scientific settings, scoring each run.
8. Run `check-stability` (`--min-agreement 4`) to retain candidates where run 1 produced a valid integer option in `{1, 2, 3, 4}` and at least 4 of 5 runs agree on correctness. Report both correctness agreement and exact-option agreement.
9. Conduct the independent human pilot on stable candidates after ethics approval, then partition distinct `layout_family_sha256` families across learning and retention sets to prevent stimulus leakage.
