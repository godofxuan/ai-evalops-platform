# S3-compatible artifact backend

Status: local contracts and complete non-integration suite `VERIFIED`; first real MinIO execution
`FAILED`; non-root volume-ownership correction `PENDING` on the next GitHub Actions run.

## Decision and scope

The existing `ArtifactStore` boundary was retained. Dataset, Run, Result, and Review services still
depend only on byte-oriented content-addressed `put_bytes` / `get_bytes` operations. The change adds
an `S3ArtifactStore`, a backend factory, backend-aware readiness, and configuration; it does not
rewrite evaluation orchestration into a cloud-specific architecture.

`boto3` is intentionally used through `asyncio.to_thread`. Artifact operations are coarse-grained
network calls, while boto3 supplies mature SigV4, credential-chain, endpoint, retry, and S3 error
handling. Hand-writing S3 authentication with the existing HTTP client would add security-sensitive
protocol code. A second asynchronous SDK stack would add session lifecycle complexity without a
measured benefit at the current artifact size limits.

## Content address and tenant ownership

Both backends derive the SHA-256 digest on the server. S3 keys are
`<prefix>/<first-two-hex>/<sha256>`, and each object stores the digest in S3 user metadata. Uploads
also send `Content-MD5` for transport integrity. Downloads verify content length, digest metadata,
and a freshly computed SHA-256 before returning bytes.

Tenant ownership is deliberately not stored as a single physical-object metadata value. Identical
content may be referenced by multiple tenants, so one tenant ID on the globally deduplicated object
would be ambiguous and could expose ownership. Existing PostgreSQL `artifact_references` remain the
tenant-authoritative metadata layer; `artifact_blobs` maps those references to the global content
digest.

## Atomic publish and dedup

S3 publication uses `PutObject` with `IfNoneMatch="*"`. A successful call publishes a complete
object. A 412 response means another publisher already owns the key; the store downloads and verifies
that object before returning `created=false`. A 409 concurrent-operation conflict is retried at most
three times, then fails closed with `ArtifactPublishConflictError`. Other client or service failures
propagate without being mislabeled as deduplication.

Local storage retains its temporary-file, flush, fsync, digest verification, and hard-link publish
path. Both implementations therefore expose the same content-addressed and deduplicated contract,
although their durability depends on the configured filesystem or object service.

## Failure and deletion semantics

Missing or corrupt objects raise `ArtifactIntegrityError`; corrupt content is never returned and is
not deleted by cleanup. Deletion first verifies metadata and bytes, then removes the known digest.
Deleting a missing object returns false. Bucket readiness uses `HeadBucket` and does not create probe
objects. Bucket creation is an operator action, so a missing/misconfigured bucket fails readiness
instead of silently creating infrastructure with application credentials.

Database reference commits and S3 deletion are not one distributed transaction. Existing cleanup
continues to delete only a known SHA after confirming it has no references. A production deployment
should additionally use bucket versioning/retention and a lifecycle or reconciliation process; this
change does not claim cross-system exactly-once deletion.

## Configuration

`EVALOPS_ARTIFACT_BACKEND=local` remains the application default. S3-compatible operation uses:

- `EVALOPS_ARTIFACT_S3_BUCKET` and `EVALOPS_ARTIFACT_S3_PREFIX`;
- optional `EVALOPS_ARTIFACT_S3_ENDPOINT_URL` for MinIO;
- region and path/virtual addressing style;
- an optional access/secret pair, or boto3's default credential chain when both are absent.

The access and secret values are `SecretStr` and must be supplied together. Compose builds a thin
image from pinned MinIO, prepares `/var/lib/evalops-minio` for UID/GID 1000 at image-build time, and
runs that non-root user with persistent `minio_data`, health checking, read-only rootfs, dropped
capabilities, and resource limits. Local storage remains selectable as a rollback/developer path.

## Test evidence

RED first failed during collection because `S3ArtifactStore` and
`ArtifactPublishConflictError` did not exist. After the storage implementation, 13 storage contracts
passed while two configuration tests still failed because backend fields and bucket validation were
missing. Adding conditional configuration made all 31 pass. A second RED failed because the backend
factory did not exist; after factory, app wiring, and readiness changes, the focused set passed.

Deployment contracts then failed five times because Compose and CI did not contain MinIO. The final
local focused set passed 66 tests. Full local validation resolved 79 locked packages, checked 295
files with Ruff formatting and lint, passed strict MyPy for 127 source files, and passed 561
non-integration tests with 12 real-service tests deselected in 368.12 seconds.

The pending GitHub test will execute 12 concurrent conditional writes against real MinIO, require one
physical creation, verify download, simulate object corruption, refuse corrupt deletion, verify
idempotent deletion, and confirm missing-bucket readiness/publish failures. Compose smoke will select
the S3 backend, provision the bucket explicitly, and require API readiness through MinIO.

## First remote negative result

GitHub Actions run `31250560395` executed source `a98a5fb`. Both jobs built/synchronized their
prerequisites, but MinIO exited during storage initialization. Compose diagnostics showed
`API: SYSTEM.storage`; PostgreSQL and Redis were healthy. The quality job's MinIO test then failed
because its `!cancelled()` contract deliberately continued after the failed startup.

Registry inspection of the exact official image showed no declared runtime user and a parent-image
volume at `/data`. The first Compose definition forced UID/GID 1000 directly onto that fresh volume,
without preparing ownership. The correction does not relax runtime hardening to root: it creates and
owns a non-parent-volume data directory during image build, switches back to UID/GID 1000, and mounts
the named volume there. Compose failure annotation ordering was also changed to put MinIO-only logs
before aggregate service logs so a future root cause is not truncated out of the bounded annotation.
