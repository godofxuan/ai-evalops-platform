# RAG Producer Artifact Integrity Contract

Status: implemented and fail-closed on branch codex/evalops-integrity-remediation-v1.

The adapter accepts only enterprise.agent-harness-result/1.0 containing an
enterprise.agent-run/1.0 producer artifact. Validation occurs before conversion.

## Required proof

1. The trajectory is non-empty.
2. Event sequence starts at 1 and is contiguous.
3. Event IDs are unique; timestamps do not move backwards.
4. Every event carries the artifact session/trace identity.
5. previous_hash equals the preceding event digest.
6. event_hash is SHA-256 over canonical JSON of the event without event_hash.
7. source_trajectory_root_hash equals the final event digest.
8. artifact_sha256 covers canonical producer JSON without artifact_sha256.
9. Top-level tool events exactly equal the tool projection from the trajectory.

Canonical JSON uses sorted keys, compact separators, UTF-8, and ensure_ascii=True,
matching producer commit e848d8e6090267b28d351758fe8d3cb557dcd586.

## Loss accounting

All producer events map into the framework-neutral trajectory. Model, tool, evidence,
claim, citation, terminal, and review interruption/resume events retain their complete
producer payload. Top-level policy decisions become explicit policy_decision events.
Metadata records source, converted, unmapped, and dropped counts plus a loss manifest.
A successful strict conversion has zero unmapped and zero dropped events.

## Failure behavior

Duplicate IDs, non-contiguous order, backwards timestamps, identity mismatch, chain
breaks, root mismatch, Artifact digest mismatch, and tool-surface mismatch all raise
RagHarnessContractError. Such artifacts cannot enter formal quality or release gates.
