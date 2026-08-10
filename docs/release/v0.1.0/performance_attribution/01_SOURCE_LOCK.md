# Instrumentation Source Lock

- Instrumentation-only code commit: `f1ecbf20d8e266eddadd85391d2c782c581ecad2`
- Scheduler-behaviour baseline: `c5e8368e6588b7684a87e44d15c99e0d320744a7`
- Production-code delta after the baseline: optional phase observer hooks and diagnostic recorder
  wiring only
- Experiment execution SHA: the immutable `GITHUB_SHA` of the dedicated diagnostic workflow
  trigger commit; the workflow writes and cross-checks it in every repetition

No `app/` or `scripts/` change is allowed between the instrumentation-only commit above and the
diagnostic trigger commit. Documentation, the dedicated workflow and its trigger are the only
permitted intervening files. If the production tree differs, the experiment is invalid.

The dedicated run is diagnostic evidence. It cannot replace workflow `31352270523`, change the
frozen 0.95 gate, mark PR #1 Ready, authorize downstream qualification or change v0.1.0 from
`NOT_READY`.
