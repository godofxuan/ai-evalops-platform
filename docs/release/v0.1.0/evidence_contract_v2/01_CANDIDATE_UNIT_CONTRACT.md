# Evidence contract v2 — candidate-unit preregistration

Status: frozen before implementation; implemented without threshold changes

## Problem statement

Schema v1 assumes every PostgreSQL selector ranks or scans eligible Jobs, so it compares every EXPLAIN
`candidate_cardinality` with `arms.csv.queue_size`. Candidate 3 changed only the fair selector: its measured statement
is `build_scheduler_round_members_statement()`, whose result set is one row per eligible Tenant in the highest-
priority round. The legacy FIFO statement still operates on Jobs.

Using one queue-size expectation for both selectors is dimensionally invalid: `eligible_tenants != eligible_jobs`.

## Schema v2 contract

### Bundle manifest

- `schema_version = 2` for newly generated fair-capacity bundles.
- schema v1 remains supported with its original semantics; it is not reinterpreted.

### Arms CSV

- add required non-negative integer `tenant_count`;
- require `1 <= tenant_count <= queue_size`;
- require the frozen distribution contract:
  - `single_tenant`: 1;
  - `balanced_multi_tenant`: 4;
  - `skew_20_to_1`: 2;
  - `many_small_tenants`: `min(queue_size, 100)`;
- unknown distributions or inconsistent counts fail closed.

### Preregistered arm identity

For schema v2, the assessor parses each expected arm ID in the production form
`fair-q{queue_size}-{distribution}-w{worker_concurrency}-b{claim_batch_size}`. The CSV row must match all four
dimensions. Expected Tenant count and EXPLAIN cardinality are derived from this preregistered identity, not from
untrusted CSV metadata alone.

### EXPLAIN records

Each schema-v2 record must include `candidate_unit`:

| Selector | Required unit | Independent expected cardinality |
|---|---|---:|
| `fair` | `eligible_tenant_round_members` | `arms.csv.tenant_count` |
| `legacy_fifo` | `eligible_jobs` | `arms.csv.queue_size` |

The assessor, not the EXPLAIN producer, chooses the expected value from the selector and arms row. A record cannot
self-certify by writing an arbitrary `expected_candidate_cardinality` field.

## Fail-closed rules

Schema v2 must fail when:

- `tenant_count` is absent, zero, greater than queue size or inconsistent with distribution;
- queue size, distribution, Worker concurrency or batch size differs from the preregistered arm ID;
- schema version is a boolean, non-integer or unsupported integer;
- selector is absent or unknown;
- candidate unit is absent or does not match selector;
- cardinality is bool, nonnumeric, nonintegral, negative or differs from independent expectation;
- coverage, source, manifest, arm or correctness checks fail.

No fairness/performance threshold changes. No current failed bundle promotion.

## Compatibility rules

- schema v1 accepted manifests continue using queue-size cardinality for both selectors because their fair selector
  was Job-ranked;
- schema v2 is required for Candidate 3 round-membership evidence;
- assessment output reports the manifest schema version it actually evaluated;
- a schema number outside the supported set fails `manifest_invalid`.

## GREEN acceptance

Before remote execution:

1. a v2 fixture matching Candidate 3 (fair=Tenant count, legacy=queue size) verifies;
2. every malformed unit/count negative fails;
3. existing schema-v1 tests remain green;
4. the preserved schema-v1 failure stays FAILED;
5. producer records v2 manifest, Tenant count and selector units;
6. Ruff, format, MyPy and focused tests pass.

Remote promotion still requires ordinary CI plus a new exact-source four-repetition targeted workflow. Local/offline
GREEN does not change release state.
