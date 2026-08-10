# Raw EXPLAIN Independence

## Problem and risk

The producer calculated `candidate_cardinality` with `summarize_explain()`. The assessor compared
that top-level value with the arm contract but never derived it from `plan`. A producer bug or a
tampered raw plan plus recomputed manifest could therefore pass: manifest integrity is not semantic
independence.

The risk affected schema v2 only. Schema v1 is historical and intentionally retains its old
top-level cardinality semantics.

## Real plan study

The preserved schema-v2 evidence showed two different selector units:

- fair: one `WindowAgg` emitted 1/2/4/100 eligible Tenant round members; underlying Job scans often
  visited 1,000 Jobs and therefore are not the fair candidate unit;
- legacy FIFO: top-level `Limit` emitted one row, while the visible `evaluation_jobs` Bitmap Heap
  Scan visited 1,000 eligible Jobs; Bitmap Index TIDs were excluded because heap visibility had not
  yet been applied.

The assessor implementation does not import or call producer `summarize_explain()`. It recursively
parses the raw document with separate code. Fair requires exactly one `WindowAgg`; legacy requires
exactly one non-Bitmap-Index `evaluation_jobs` relation node. Missing or multiple candidates fail
closed. Rows/loops must be finite, integral and nonnegative.

## RED and GREEN

Commit `03bc78a` added disagreement, recomputed-manifest tampering, real-shaped fair/legacy,
missing-node and ambiguous-node tests. The focused RED run produced 24 failures overall; all four
raw-plan rejection tests returned the old `VERIFIED` result.

Commit `7eea650` added the independent parser. The release-evidence suite then had 48 passes and
only the three not-yet-implemented false-empty tests failed. Ruff and formatting passed.

The four immutable schema-v2 rep bundles from workflow `31352270523` were reassessed with the new
parser: each remained `VERIFIED`, with 16 arms, four EXPLAIN repetitions and no blocker. No JSON or
manifest was rewritten.

## Why not reuse producer code

Calling `summarize_explain()` twice would reproduce the same bug twice. A generic “maximum Actual
Rows anywhere” parser was also rejected because fair Job scans are intentionally much larger than
the Tenant candidate set, and top-level Limit hides the legacy candidate set.

## Trade-off and claim boundary

The parser is deliberately strict about known PostgreSQL shapes. A future legitimate plan shape may
fail closed and require a contract update. After this repair it is accurate to say current schema-v2
raw cardinalities are independently checked for the registered fair/legacy shapes; it is not a
universal PostgreSQL-plan verifier or protection against every evidence manipulation.

Resume/interview wording: “I removed a common-mode evidence failure by independently parsing raw
PostgreSQL plans according to selector-specific units, with fail-closed ambiguity handling.”
