import asyncio
import os
from typing import Any, cast
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from app.artifacts.storage import ArtifactIntegrityError, S3ArtifactStore, S3Client

pytestmark = pytest.mark.integration


def _integration_configuration() -> tuple[str, str, str, str]:
    if os.getenv("EVALOPS_RUN_MINIO_INTEGRATION") != "1":
        pytest.skip("set EVALOPS_RUN_MINIO_INTEGRATION=1 for real MinIO integration")
    return (
        os.environ["EVALOPS_TEST_MINIO_ENDPOINT"],
        os.environ["EVALOPS_TEST_MINIO_ACCESS_KEY"],
        os.environ["EVALOPS_TEST_MINIO_SECRET_KEY"],
        os.environ["EVALOPS_TEST_MINIO_BUCKET"],
    )


async def test_real_minio_upload_download_dedup_failure_and_concurrent_publish() -> None:
    endpoint, access_key, secret_key, bucket = _integration_configuration()
    client = cast(
        S3Client,
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path"}),
        ),
    )
    raw_client: Any = client
    try:
        raw_client.create_bucket(Bucket=bucket)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code not in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}:
            raise

    store = S3ArtifactStore(
        client=client,
        bucket=bucket,
        prefix=f"integration/{uuid4().hex}",
    )
    content = b'{"case_id":"minio-case"}\n'

    await store.check_ready()
    published = await asyncio.gather(*(store.put_bytes(content) for _ in range(12)))

    assert sum(item.created for item in published) == 1
    assert len({item.sha256 for item in published}) == 1
    assert await store.get_bytes(published[0].sha256) == content

    key = published[0].relative_path.as_posix()
    raw_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=b"tampered",
        Metadata={"sha256": published[0].sha256},
    )
    with pytest.raises(ArtifactIntegrityError):
        await store.get_bytes(published[0].sha256)
    with pytest.raises(ArtifactIntegrityError):
        await store.delete_bytes(published[0].sha256)

    restored = b"restored under a new digest"
    restorable = await store.put_bytes(restored)
    assert await store.delete_bytes(restorable.sha256) is True
    assert await store.delete_bytes(restorable.sha256) is False


async def test_real_minio_missing_bucket_fails_readiness_and_publish() -> None:
    endpoint, access_key, secret_key, bucket = _integration_configuration()
    client = cast(
        S3Client,
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path"}),
        ),
    )
    store = S3ArtifactStore(
        client=client,
        bucket=f"{bucket}-missing-{uuid4().hex}",
        prefix="integration/failure",
    )

    with pytest.raises(ClientError):
        await store.check_ready()
    with pytest.raises(ClientError):
        await store.put_bytes(b"must not publish")
