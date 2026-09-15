# Learning grading and calibration notes

Scope: `app/product_experiments/learning_grading.py` and its public-API unit tests.
This is optional local learning analysis, not a registered official evaluator,
release gate, threshold change, or claim of genuine human verification.

## Public contracts

- `grade_answer(reference_answer, actual_answer, *, profile)` returns strict,
  versioned `GradeResult`. Both profiles are code registered behind
  `DiagnosticGrader`; there is no dynamic import, eval, network, model SDK, or new dependency.
- `normalized_exact_v1` reuses the existing `reference_answer` evaluator.
- `json_structural_v1` reuses `decode_evidence_json` (depth 64, duplicate-key and
  nonfinite rejection) and the registered `tool_argument_validity` structural
  comparator. Objects ignore order; arrays retain order; bool is not a number;
  numeric 1 equals 1.0.
- Invalid reference JSON returns `grading_status=INVALID_REFERENCE`, with a zero
  sentinel and explicit limitation. This is an input/grader problem, not a
  candidate failure. Such decisive reviews are excluded from agreement.
- `observation_identity(row, *, profile)` binds case ID, arm, prompt, reference,
  answer, profile and grade/observation schema versions through canonical SHA-256.
  It emits no plaintext identifiers. Hashes bind content; they are not signatures
  or evidence of an authenticated reviewer.
- `make_review_packet(rows)` accepts case_id, arm, prompt, reference_answer, answer,
  and optional profile (default normalized_exact_v1). It returns a Pydantic
  `ReviewPacket`, deterministically ordered by item identity. Annotation items
  expose only item_id, prompt, reference_answer, answer, and profile. No automated
  score, case ID, or arm label is emitted. Rubric and packet contents bind the hash.
- `calibrate_reviews(packet, reviews)` accepts the model or its JSON-mode dump.
  Each review must explicitly provide packet_hash, item_id, reviewer_id,
  evidence_kind (`HUMAN_DECLARED` or `SYNTHETIC`), and label
  (`PASS`, `FAIL`, `UNSURE`, or null). Stale hashes, unknown IDs, duplicate items,
  unknown fields and absent declarations are rejected. One review per item is
  supported; repeated reviewers may cover different items. This is automated-vs-
  declared-label agreement, not inter-human consensus.

## Coverage and interpretation

`total_items = missing_reviews + unsure_reviews + null_reviews + ungradable_reviews
+ paired_labels`. `submitted_reviews = total_items - missing_reviews`.
UNSURE, null, missing and invalid-reference reviews never become agreement pairs.
Confusion cells use automated PASS as the positive prediction: false_pass means
automated PASS / declared FAIL; false_fail means automated FAIL / declared PASS.
Exact agreement and Cohen kappa reuse `app/reviews/agreement.py`; undefined metrics
remain null rather than claiming perfect agreement.

Top-level statistics are pooled descriptive results. `by_evidence_kind` separately
reports HUMAN_DECLARED and SYNTHETIC statistics, and `evidence_counts` includes
decisive and abstaining submitted reviews. Every report is `DESCRIPTIVE_ONLY`,
`formal_status=NOT_EVALUATED`, `human_verification=NOT_VERIFIED`, even when all
synthetic labels agree. HUMAN_DECLARED is an unauthenticated declaration. No real
human labels were supplied or manufactured for this implementation; labels in
unit tests are fixtures, including fixture HUMAN_DECLARED rows.

Bounds exported for workflow preflight: `MAX_REVIEW_ITEMS=1000`,
`MAX_TEXT_BYTES=256000` UTF-8 bytes per text field, and `MAX_PACKET_BYTES=8000000`
canonical serialized packet bytes. Large diagnostic batches must be split; these
optional diagnostic limits do not silently change official run semantics.

## Vertical TDD record

Each row was added and run red, then minimally implemented and rerun green.

| Behavior slice | Observed red | Subsequent focused green |
| --- | --- | --- |
| Registered normalized diagnostic | 1 import/collection error | 1 passed |
| Strict JSON structure and numeric types | 8 failed, 1 passed | 9 passed |
| Unknown profiles and strict result validation | 1 failed, 9 passed | 10 passed |
| Stable blind packet / bound observation identity | 1 failed, 10 passed | 11 passed |
| Missing reviews cannot claim agreement | 1 failed, 11 passed | 12 passed |
| Coverage, all confusion cells and evidence strata | 1 failed, 12 passed | 13 passed |
| Review binding and explicit declarations | 4 failed, 19 passed | 23 passed |
| Text, depth and packet bounds | 1 failed, 23 passed | 24 passed |
| Invalid references excluded from candidate failure | 1 failed, 24 passed | 25 passed |
| Profile, evidence and result consistency | 3 failed, 25 passed | 28 passed |

One intermediate test edit misplaced an assertion, producing an unrelated NameError;
it was corrected and the relevant red run repeated before implementation. Existing
file edits used the apply_patch executable after the sandbox helper failed; the
Windows batch wrapper did not preserve multiline patch arguments.

Final focused regression command included learning_grading, existing agreement,
and existing evaluator tests: **39 passed**. `ruff check` on module/tests and strict
`mypy` on the module both passed. No dependency or lock changes were made.

## Lessons

- Keep reference-data failure separate from candidate failure before aggregating.
- Blind annotation does not require exporting scores or arm metadata: recompute
  diagnostics from the bound packet when descriptive calibration is requested.
- A single coverage equation and explicit one-review-per-item rule prevent
  abstentions or duplicate labels from inflating agreement.
- Reusing the registered evaluator and bounded strict decoder avoids a divergent
  unofficial definition of normalized text, JSON types, or parser safety.

## Follow-up: legacy CLI output preflight

Bounded follow-up scope: `scripts/run_product_experiment.py` and
`tests/unit/scripts/test_product_experiment_preflight.py`. No artifact manifest,
historical policy, score, gate, or new workflow script changed.

The original `_run` called the targets before `write_product_artifacts` inspected
the output destination. A real loopback HTTP reproduction, using two valid cases
and both HTTP arms, observed **four requests before failure** for an existing
nonempty output directory. The same late failure reproduced for an existing
export lock and a filesystem write denial. Invalid SHA values similarly reached
target execution before final result validation.

Ranked hypotheses were (1) late destination validation, (2) leaf-only link checks,
and (3) late lock/write-permission validation. The public CLI-callable tests
confirmed all three. CLI, runner, provider, aggregation, and exporter are real;
only DNS identity and the HTTP transport boundary are fixture-injected. Requests
still traverse actual loopback sockets and are counted by the target server.
The write-denial case injects a failure only at the filesystem write boundary.

Fix: before target execution, reject nonempty/non-directory output paths and
symlinks/junctions in the destination or any ancestor; acquire the existing
exclusive sibling export lock; perform a small staging-file write; clean up the
probe and our own lock. An existing writer's lock is never removed. Export repeats
the destination/link check and re-acquires its ordinary lock. Both absent and
existing empty destination directories remain accepted. Explicit or discovered
EvalOps SHA must be exactly 40 lowercase hex characters before output writes or
target calls. Invalid SHA remains a safe `experiment_input_invalid` exit 2.
`--validate-only` does not acquire locks or touch output, even when that output is
nonempty and another writer's lock exists.

This is an early availability/write probe, **not race immunity**: the preflight
reservation is deliberately released before target execution to preserve the
existing exporter lock/API. Permissions, disk capacity, or another writer can
still change afterwards. The tiny write probe does not reserve final bundle size.

Vertical TDD observations:

| Slice | Red | Green |
| --- | --- | --- |
| Nonempty output incurs no calls | 1 failed (4 actual requests) | 1 passed |
| Existing lock incurs no calls | 1 failed, 1 passed | 2 passed |
| Write denial incurs no calls | 1 failed, 2 passed | 3 passed |
| Leaf and ancestor junctions | 2 failed, 3 passed, 2 skipped | 5 passed, 2 skipped |
| Invalid SHA / validate-only syntax | 8 failed, 5 passed, 2 skipped | 13 passed, 2 skipped |

Additional compatibility regressions cover real execution into absent/empty
outputs, unchanged manifest verification, dry-run byte preservation, and safe CLI
error output. Final new suite: **17 passed, 2 skipped**. Both skipped cases require
directory symlink creation, unavailable on this Windows host (privilege 1314);
both real Windows junction cases passed. The existing CLI/export/verification
regression run (before adding the final safe-error test) was **62 passed, 3 skipped**.
The additional existing-suite skip has the same filesystem symlink restriction.
Ruff and strict mypy passed for the CLI and its new test file. A first reproduction
fixture used one case, hit the established two-case minimum, and was corrected
before observing the actual bug. No debug logging or temporary prototype remains.

Prevention lesson: resource-affecting execution needs a CLI-level, no-target-call
regression for output prerequisites; testing only the artifact writer cannot
detect expensive requests occurring before a perfectly correct writer rejection.
