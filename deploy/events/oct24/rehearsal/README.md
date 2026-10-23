# Private event rehearsal

These operator tools exercise the real participant CLI and Azure event proxy.
They do not simulate research or bypass publication gates. Keep the run directory
private: it contains account-specific paths and activity, not provider keys.

`guard.py` enforces one reserved spending cap across local lab processes. Start
it with `--run-dir`, the participant's private `--env`, and `--cap`. It writes its
loopback port to `guard-port`. `worker.py` takes that port, the same `--run-dir`,
and a local `--submission`; it strips inherited provider credentials, uses the
normal event connection, and records actual Researcher, executor, Writer and
reviewer intervals. The guard supports non-streaming model calls only. Use `worker.py --finish-queued` for an explicit
completion stage: execute already prescribed tests and run the normal Analyst
and Writer/three-reviewer path, without asking for further research proposals.

`status.py RUN_DIRECTORY` reports measured concurrency and failures.
`analyze.py RUN_DIRECTORY --catalogue deploy/events/oct24/starter-manifest.json`
reports the first successful, registered campaign measurement per idea and seed
0–4 at the frozen starter settings. It excludes failed runs, orphan campaign
IDs, different settings and follow-up seeds. Inspect fresh replications separately;
do not relabel historical evidence to repair provenance.

A reserve is released only with an observed usage response or a definitive
non-billable rejection. Ambiguous responses remain held across guard restarts.
Include any separately recorded provider spending in the owner's overall ceiling.
The event proxy separately enforces the normal shared participant/event budgets.

For updates, record owner pause steering, wait for acknowledgement **and all
in-flight model operations to finish**, then stop workers and update the hub.
A completed Researcher turn can include several internal model requests; an
empty experiment queue alone does not prove that spending has stopped. Restart
with preserved queues, campaign IDs, raw measurements and the same run directory.
Never disable live-daemon safety checks to rush a restart.

At completion, pause and stop all workers, retain ambiguous reservations, reconcile
the guard with the authoritative participant ledger, and retain a private results
report. Keep research private; pushing application fixes does not authorize public
release of papers or evidence.
