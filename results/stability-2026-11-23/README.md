# Benchmark and stability results — 23 November 2026

The full benchmark contains 1,488 valid records. Four repeat runs each contain
160 valid responses, with no outstanding request errors or incomplete outputs
in the final scoring summaries. These repeats are a stratified candidate sample,
not estimates of full-pool category accuracy.

The frozen 160 candidates have five valid observations each (full-001 plus r2–r5).
The implemented stability criterion is at least four of five correctness states
matching the first-run correctness state. Participants will receive the first-run
advice, not a majority-vote replacement. Correctness stability does not require
the same wrong option on each run.

| Category | Stable | First-run correct | First-run incorrect | Unique stable layouts |
|---|---:|---:|---:|---:|
| MRT | 31 | 13 | 18 | 31 |
| MPFB | 21 | 11 | 10 | 21 |
| JLO | 34 | 20 | 14 | 34 |
| PTT | 33 | 31 | 2 | 19 |
| Total | 119 | 75 | 44 | 105 |

The two stable PTT errors (PTT_vision-00116 and PTT_vision-00375) belong to
different layout families. Their human difficulty is not yet known. If each
participant sees each layout at most once, PTT permits at most 19 distinct-layout
trials across learning and retention before further pilot exclusions.
For example, 10 learning plus 10 retention PTT trials would exceed this limit.
MPFB has only 21 stable layouts before human difficulty selection.

## Files

- stability_summary.json: category totals, stable IDs, and filter settings.
- stability_summary.csv: all 160 candidates, including excluded candidates,
  first-run advice/correctness, valid-run counts, and agreement measures.
- run_summaries.json: full-run and repeat-run scoring summaries.

Raw API responses, request bodies (including encoded images), recovery journals,
and local datasets remain in local archives and are not included in this public
result export. Existing dataset licensing requirements still apply.

## Technical recovery

Some r4/r5 requests required transport recovery. Original metadata and successful
HTTP 200 responses were preserved; failed attempts and interruptions were archived.
Recovery used a 600-second timeout and sequential execution; model, prompt,
reasoning effort, image detail, and output-token ceiling remained unchanged.
Connection errors and exhausted-credit errors were recovered after replenishment.
The implementation and amendments are documented in recover_timeouts.py and
docs/RUN_PLAN.md. This export reports final successful observations, not total
billable attempts.

## Next decision

Use the stable candidates for an independent human difficulty pilot, assigning
different variants of a shared scene to different participant lists. Fix learning
and retention membership by layout family. Final trial counts, target reliability,
eligible disagreement counts, and power remain to be established using pilot
results and simulation. Do not relax the stability threshold post hoc simply to
restore category counts.
