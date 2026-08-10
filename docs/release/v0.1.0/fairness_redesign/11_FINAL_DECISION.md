# Candidate 3 final release decision

Status: `NOT_READY_TARGETED_NEGATIVE_SCALING`; scheduler development stopped

Candidate 3 is the one authorized bounded redesign. Its correctness and frozen targeted fairness workload passed.
The preregistered schema-v2 repair closed the prior EXPLAIN unit mismatch, and targeted run `31352270523` completed
four verified repetitions, 64 arms and 6,400 terminal Jobs.

Release is still rejected because single, balanced and 20:1 median 4-to-8 Worker throughput ratios are
`0.782511`, `0.772797` and `0.796214`, below the required 0.95. Many-small passed at `1.014063`, but the gate requires
every distribution.

PR #1 remains Draft. There is no merge, tag or GitHub Release. Capacity, same-runner, current fault and formal
scaling are `NOT_RUN_STOPPED`. No Candidate 4, parameter tuning, threshold/workload change or gate redefinition is
authorized in this stage.
