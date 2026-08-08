FROM minio/minio:RELEASE.2025-09-07T16-13-09Z

USER 0:0
RUN mkdir -p /var/lib/evalops-minio \
    && chown 1000:1000 /var/lib/evalops-minio

USER 1000:1000
