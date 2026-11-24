# Final MPFB extension — 24 November 2026

All 40 additional repeat responses are valid: ten candidates in each of four
rounds. Each candidate has five valid observations including full-001. Five of
ten new layouts pass the frozen stability criterion: two first-run AI-correct
and three first-run AI-incorrect. No additional candidate batch will be selected.

## Frozen selection and separate reporting

The amendment and ten IDs were committed before paid repeats (75dbd9b). Selection
used the existing picker and seed 20261119, excluded all original candidate
selection groups, and selected one item per remaining MPFB layout. The resulting
five-correct/five-incorrect split used four seeded minority-stratum promotions.
These are correctness-stratified candidates, not a random accuracy estimate of
the full MPFB pool. See ../../manifests/mpfb_extension_2026-11-23/ and
../../docs/RUN_PLAN.md for the frozen rule and provenance.

The original 160 candidates, 119-item stability report and first-run scores are
unchanged; their hashes were checked against the pre-extension provenance.
This directory reports the extension separately. The combined ID list is a
researcher candidate inventory, not a participant trial list or a new analysis
that replaces either batch.

## Stable extension items

| Item ID | First-run advice | Gold answer | First-run correct | Correctness agreement / 5 | Exact-option agreement / 5 |
|---|---:|---:|---:|---:|---:|
| MPFB_vision-00036 | 1 | 4 | No | 5 | 5 |
| MPFB_vision-00050 | 3 | 4 | No | 5 | 1 |
| MPFB_vision-00052 | 3 | 3 | Yes | 4 | 4 |
| MPFB_vision-00083 | 4 | 3 | No | 5 | 4 |
| MPFB_vision-00107 | 3 | 3 | Yes | 4 | 4 |

Stability requires at least four of five correctness states to match the first
run. It does not require identical option choices. In particular, item 00050
is consistently incorrect but its wrong option varies. Participant advice remains
the first-run option (3), not a majority-vote replacement. Gold answers in this
report are researcher-only and must not appear in participant instructions.

## Updated candidate inventory

| Category | Original stable | Extension stable | Combined stable | First-run correct | First-run incorrect | Unique stable layouts |
|---|---:|---:|---:|---:|---:|---:|
| MRT | 31 | 0 | 31 | 13 | 18 | 31 |
| MPFB | 21 | 5 | 26 | 13 | 13 | 26 |
| JLO | 34 | 0 | 34 | 20 | 14 | 34 |
| PTT | 33 | 0 | 33 | 31 | 2 | 19 |
| Total | 119 | 5 | 124 | 77 | 47 | 110 |

PTT remains unchanged, including its 19-scene cap and two stable error items.
Independent human difficulty selection, difficulty matching, seeded learning/
retention allocation and simulation-based trial counts remain to be fixed before
the human pilot. This report does not determine that design.

## Transport recovery and spending

Initial execution and standard retries encountered timeouts and depleted credits.
A committed transport amendment (e20033a) used sequential requests, a 900-second
SDK timeout, zero SDK automatic retries, a per-invocation request cap and immediate
stop on unsuccessful responses. A connection failure in the six-request pass was
subsequently recovered in a one-request pass. Scientific payload and settings,
original run metadata and all HTTP 200 records were preserved. Local archived
failures and recovery journals retain provenance. Forty is the number of final
valid repeat responses, not the number of billable attempts. Local successful
usage cannot establish total billed cost of timed-out/server-side work.

## Files and materials

- stability_summary.json and .csv: final extension totals and all ten candidates.
- run_summaries.json: final scoring summaries for all four extension rounds.
- combined_stable_candidate_ids.json: 124 unique IDs; original plus extension.
- verification.json: original-source digests checked unchanged and final-report hash.

The five-question material archive and browsable question folders are local:
local/mpfb_extension_materials_2026-11-24/ and
local/mpfb_extension_questions_2026-11-24/index.html. Their 25 source PNGs were
hash-verified, with original option order preserved. These are researcher materials,
not a Gorilla import or the exact JPEG/low-detail API image rendering. Original API
format instructions are separated from the human-readable previews. Stimulus
images, raw responses, encoded request payloads and recovery journals are not
included in this public export.
