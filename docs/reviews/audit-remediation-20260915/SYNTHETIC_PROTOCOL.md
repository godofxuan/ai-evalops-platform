# Frozen platform fault experiment, v1

Frozen before first matrix execution. This is synthetic platform validation, not model
quality A/B, not an extension of the historical 632 benchmark calls.

- One authenticated durable AGENT_TOOL_USE experiment, 20 cases × 2 arms = 40 planned Jobs.
- Same deterministic target responses for both arms except baseline case17 crashes after
  the real HTTP response and before database acceptance; candidate17 is the normal control.
- Case00–07: valid controls (canonical/legacy/equal aliases, duplicate/excess citation,
  wrong answer and observed tool error). Case08: first HTTP body times out, second succeeds.
- Case09: invalid HTTP JSON. 10: conflicting terminal pair. 11: 100001-character answer.
- Case12: missing agent terminal observation (accepted but insufficient evidence).
- Case13: conflicting citation aliases. 14: numeric citation ID. 15: whitespace ID.
- Case16: unresolved citation. 17: crash/recovery/late stale commit. 18–19: queued cancellation.
- Expected per arm: 12 accepted, 6 failed, 2 cancelled. Planned denominator remains 20 per arm.
- Expected total: 24 unique accepted results, 12 execution failures, 4 cancelled;
  39 attempts and 39 real synthetic HTTP requests (36 first attempts + 2 timeout retries
  + 1 repeated call after baseline17 crash). No call for the 4 cancelled Jobs.
- Retry maximum2, constant bounded retry delay. No best-of repeats, gold changes or removal.
- Six late-phase Job rows are deliberately held by test-only PostgreSQL barriers.
  Baseline17 is released alone, crashed, reaped and recovered; candidate17 is released next;
  then queued18–19 cancelled. Priorities freeze phase ordering, not production scheduler policy.
- Public DNS/peer mapping is an explicit injected test transport to a real loopback HTTP
  server. It does NOT prove public TLS/DNS or production SSRF deployment behavior.
- Raw data is synthetic. Export private+public bundles, stop target, offline recompute,
  assert every planned identity appears once, keep per-Job attempt/call counts and failures.
- Overall quality must not PASS. Accepted observations are not proof of model quality.
- Environment errors or harness failures are retained with distinct execution directory;
  debugging reruns are not independent quality samples or statistical replicates.
