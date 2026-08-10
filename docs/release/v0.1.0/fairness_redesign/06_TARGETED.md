# Candidate 3 targeted qualification

Status: `NEGATIVE_SCALING`; complete evidence preserved; stop condition reached

## Identity

| Field | Value |
|---|---|
| scheduler source | `02f5e680e71d05c76c145da6895122a2cf04ba14` |
| schema-v2 qualification source | `91acdba9f5b5f1a84fb03640382c9e4871364afe` |
| ordinary CI | push `31351821014`, PR `31351825433`, both SUCCESS |
| targeted workflow | `31352270523` |
| evidence commit | `15bab58150385c9a39778d64a3e4163c10892ecc` |
| artifact | `targeted-gh-31352270523-1`, 1,395,629 bytes |
| digest | `sha256:6b5f68821b90ee6bdbb36d66aba0087864ca2048ac356ec3cb701e378d0c120f` |
| protocol | queue 1000; four distributions; Workers 1/2/4/8; batch 1; four repetitions |

## Completed evidence

All four repetition commands succeeded. Every rep bundle is schema 2 and independently `VERIFIED`; each contains
16/16 arms and 1,600/1,600 unique terminal Jobs. Across four reps, all 64 arms completed and every correctness/fencing
counter remained zero. The frozen 20:1 application receipt positions were `2/2/2/2` in every repetition.

The selector-unit contract is complete: 256 fair EXPLAIN records count eligible Tenant round members with expected
cardinalities 1/4/2/100, and 256 legacy records count 1000 eligible Jobs. The old cardinality mismatch is absent.

## Performance decision

| Distribution | w4 median Jobs/s | w8 median Jobs/s | Ratio | Status |
|---|---:|---:|---:|---|
| single Tenant | 24.190086 | 18.929004 | 0.782511 | NEGATIVE_SCALING |
| balanced | 44.752825 | 34.584871 | 0.772797 | NEGATIVE_SCALING |
| 20:1 | 32.700255 | 26.036396 | 0.796214 | NEGATIVE_SCALING |
| many-small | 42.245796 | 42.839905 | 1.014063 | VERIFIED |

The contract requires all four ratios to be at least 0.95. The assessment step therefore returned nonzero, while
artifact upload, evidence commit and cleanup still succeeded.

## Decision

No failed arm or result was deleted. No threshold, workload, Worker, batch, seed, retry, pool, sleep or lease
parameter changed. No Candidate 4 or immediate retry is authorized. Capacity, same-runner, fault and formal are
`NOT_RUN_STOPPED`.

Historical run `31327388006` remains the immutable schema-v1 evidence-contract failure and is not the current
performance verdict.
