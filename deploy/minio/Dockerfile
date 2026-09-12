# Same release, official registry; pin bytes to avoid mutable-tag drift.
FROM quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e

USER 0:0
RUN mkdir -p /var/lib/evalops-minio \
    && chown 1000:1000 /var/lib/evalops-minio

USER 1000:1000
