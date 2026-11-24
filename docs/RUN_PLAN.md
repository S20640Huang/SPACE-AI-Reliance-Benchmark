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

After the user confirmed credit replenishment, recovery eligibility was extended
to saved APIConnectionError records and HTTP 429 responses whose error code is
exactly credit_balance_exhausted. Other unrecognised errors remain blocked.
The same payload checks, archived attempts, original metadata and HTTP 200
exclusions apply; model and generation settings are unchanged.

## Final MPFB candidate extension amendment (2026-11-23)

Trigger: the original 160-candidate batch is complete, with 119 stable items,
including 21 MPFB items from the original 40 selected MPFB layouts. Following
Mark's instruction, include the remaining 10 MPFB layouts before independent
human difficulty pilot data are collected. Gorilla interface/export self-tests
are technical checks and are not selection evidence. This is the final candidate
batch: no replacement or further expansion based on repeat outcomes or later
human performance. The expectation of about five additional stable layouts is
not a stopping rule. PTT and all other categories retain their existing pools.

Use the existing picker with seed 20261119, restricted to MPFB_vision, target 10.
Exclude all original 160 candidate IDs AND their selection groups; for MPFB this
excludes all 40 originally selected layouts, including layouts whose candidates
failed stability. Select exactly one item per remaining layout. Strata use valid
first-run strict correctness from full-001. Initially choose a representative
uniformly within each layout, then use the existing seeded mixed-layout promotion
rule to aim for five correct and five incorrect representatives. If a stratum is
unavailable, fill the shortfall from the other stratum and report it; do not reroll
seeds. In this draw four representatives were promoted to the scarce stratum,
resulting in exactly five correct and five incorrect items across ten layouts.

Frozen IDs (also in manifests/mpfb_extension_2026-11-23/candidate_ids.json):
- First-run correct: MPFB_vision-00010, MPFB_vision-00027,
  MPFB_vision-00052, MPFB_vision-00076, MPFB_vision-00107.
- First-run incorrect: MPFB_vision-00036, MPFB_vision-00050,
  MPFB_vision-00083, MPFB_vision-00120, MPFB_vision-00135.

The same folder contains the frozen original exclusion IDs, picker summary, and
provenance with layout hashes and SHA-256 digests of input scores, manifest,
configuration, original candidate list and original stability summary. Offline
verification reproduced the original 160 IDs unchanged and confirmed the new
layout set equals all 50 MPFB layouts minus the original 40.

Commit this amendment, picker changes, tests and frozen IDs before any paid call.
Keep config.json unchanged: gpt-5.4-2026-03-05, medium reasoning, 32768 output-token
limit, low image detail. Use full-001 as run 1; run four additional repeats of the
frozen ten IDs as mpfb-extension-r2 through mpfb-extension-r5 (40 planned requests,
excluding technical retries). Preserve completed responses. Technical failures
follow the documented retry/recovery policy, never answer-based reruns.

Apply the original criterion: at least four of five valid correctness states must
match the FIRST RUN's correctness state. Report exact-option agreement separately;
participant advice remains the first-run answer. Report this extension separately
in runs/mpfb_extension_stability_summary.json and its CSV companion. Preserve the
original runs, candidate list and stability summary unchanged. Publish the separate
extension summary when complete, even if fewer than five layouts pass. This
amendment does not settle the separate pre-pilot human selection/allocation rule.

## MPFB bounded transport recovery amendment (2026-11-24)

After standard transport retries, 34/40 extension responses are valid. Remaining:
mpfb-extension-r3: MPFB_vision-00050 and MPFB_vision-00135 (timeouts);
mpfb-extension-r5: MPFB_vision-00050, MPFB_vision-00107, MPFB_vision-00120,
MPFB_vision-00135 (credit_balance_exhausted). Repeated 180-second timeouts with
SDK max_retries=2 can incur unobserved server-side token charges. Local successful
usage is not a complete billing record and must not be presented as total spend.

Before further paid recovery, commit this transport amendment. recover_timeouts.py
now accepts the frozen extension candidate file, defaults to sequential requests,
900-second SDK timeout, zero SDK automatic retries, and at most six requests per
invocation. Stop immediately on a non-200 or non-completed response, save the
journal and score the affected run. Do not automatically rerun after this stop.
The timeout is not a guaranteed total wall-clock deadline. This request cap is
per invocation, not an account spending cap or a promise of successful completion.

Scientific payload, 32768 maximum output tokens, first-run advice, candidate IDs,
original metadata and all HTTP 200 records remain unchanged. Existing archived
failures and new recovery journals preserve provenance. Four completed rounds are
required before final extension reporting. Use dry-run validation before execute;
no change to the original 119-item stability report.
