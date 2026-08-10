# v0.1.0 RC current-candidate load status

Conclusion: current targeted load evidence is complete and `NEGATIVE_SCALING`. Current capacity, same-runner, fault
and formal load qualifications are `NOT_RUN_STOPPED`, not `VERIFIED`.

## Current evidence

- Candidate 3 scheduler source: `02f5e680e71d05c76c145da6895122a2cf04ba14`;
- schema-v2 qualification source: `91acdba9f5b5f1a84fb03640382c9e4871364afe`;
- ordinary CI: push `31351821014` and PR `31351825433`, both PASS;
- targeted workflow: `31352270523`, failed only at repeated self-scaling assessment;
- evidence bot commit: `15bab58150385c9a39778d64a3e4163c10892ecc`;
- artifact: `targeted-gh-31352270523-1`, 1,395,629 bytes;
- digest: `6b5f68821b90ee6bdbb36d66aba0087864ca2048ac356ec3cb701e378d0c120f`;
- four rep bundles: schema 2, 16/16 arms each, no blockers;
- aggregate: 64/64 arms and 6,400/6,400 unique terminal Jobs;
- 20:1 positions: `2/2/2/2` in every repetition;
- formal targeted result: `NEGATIVE_SCALING` for single, balanced and 20:1;
- many-small targeted result: VERIFIED;
- old EXPLAIN cardinality blocker: closed for schema v2, retained only in immutable historical run `31327388006`.

Allowed claims: exact-workload targeted correctness/fairness passed; complete repeated performance evidence rejected
four-to-eight Worker scaling in three distributions. Forbidden claims: linear scaling, production capacity,
production-ready performance, universal fairness or v0.1.0 release readiness.

## Historical evidence boundary

Historical capacity belongs to `9987a28`/`31272789199`; historical A-I x3 fault belongs to
`70a9b2b`/`31275450353`; historical broken-fair formal belongs to `6acf72c`/`31274490704`; pre-fair formal belongs to
`15e7ac2`/`31177702100`. None may fill a current downstream gate.
