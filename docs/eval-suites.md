# Lab evaluation suites

`efferents evals generate --submission PATH` makes one budgeted model call through
the lab's existing provider settings. Event participants use their own proxy token;
the upstream Azure key stays on the hub. The command writes `eval-suite.json` with
lab-specific metric histories and image artifact kinds, validates column references,
and records model and input/output hashes in `context/eval-suites/`. Existing suites
are reused. `--replace` archives the previous suite before regeneration.

The lab author must implement the metrics, baseline, relevant uncertainty, and
sample/error galleries in the real executor. Declare metrics in `metrics.panels`
and emit PNG artifact paths in the result envelope. Use unique filenames. Model
generation configures views; it cannot invent measurements or execute new code.
Run smoke, inspect the emitted files, then run `efferents evals validate`. Smoke
measurements should have an explicit eligibility constraint excluding them from
scientific conclusions. Viewing the console makes no model calls.

Set `EFFERENTS_GENERATE_EVAL_SUITE=1` to generate a missing suite at daemon startup
and validate existing suites before execution. Generation failure blocks startup
with a diagnostic. Offline trials remain available without a model key.

Eval plots use persisted eligible runs, and hover labels identify the source run.
Missing suites and missing samples remain visible as missing; they are not scored
as successful evaluations. Existing evidence and run artifacts are retained.

Event configuration enables `EFFERENTS_OWNER_EVAL_SYNC=1` (the historical flag
name). Heartbeats upload bounded metric histories and PNG images to the
authenticated hub, where every signed-in participant can view them. Only the
owner can steer or report for a lab. Anonymous viewers cannot retrieve evals.
The journal feed remains separate. Source, configs, credentials and datasets
are not in the snapshot. The local lab is the complete record; hosted galleries
are bounded and show their last sync time. Participant tokens expire 48 hours
after joining; browser session cookies also last 48 hours from sign-in.
