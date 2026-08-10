# Formal-run preflight fix addendum

- Failed preflight workflow: `31420616109`
- Trigger/execution SHA: `16bc33b7ce158416a174e358d175cc40d868c713`
- Evidence commit: `bb8366a`
- Artifact SHA-256: `44bade30f2a5e93a27f13e6fc84760426dcec77d6958eb02b381bbfee5f2988a`
- Evidence subtree SHA: `f7c94423e3164e3fd3c6ba188ebce0a8c786ae0d`
- Manifest audit: 6 listed, 6 actual, zero missing/extra/size/hash mismatch
- OFF/ON repetitions executed: **0/0**

The source lock, historical locks, PostgreSQL/Redis startup and migrations all passed. The workflow
then stopped in its environment-recording preflight because uv's locked virtual environment does
not seed the `pip` Python module:

```text
Python 3.12.13
.venv/bin/python3: No module named pip
```

This is an evidence-workflow compatibility issue, not a telemetry, workload, database or scheduler
failure. No repetition directory or assessment was created. The `always()` preservation path still
uploaded and committed the partial environment evidence, demonstrating that negative/preflight
evidence is not discarded.

The only permitted workflow change is replacing remote `python -m pip check` with `uv pip check`,
which checks the same locked environment without requiring pip to be installed inside it. The local
baseline `python -m pip check` result remains separately recorded. No behavioral source path,
measurement code, arm, order, frequency, threshold, stop rule or interpretation changes.

The next formal attempt must use a new trigger SHA and workflow-run identity. It may execute the
original exactly-eight-run protocol because this preflight attempt produced zero measurement
observations.

