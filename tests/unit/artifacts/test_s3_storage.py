import asyncio
import base64
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from app.artifacts.storage import (
    ArtifactIntegrityError,
    ArtifactPublishConflictError,
    S3ArtifactStore,
)


class FakeS3Error(Exception):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        }


class FakeBody(BytesIO):
    closed_by_store = False

    def close(self) -> None:
        self.closed_by_store = True
        super().close()


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.get_bodies: list[FakeBody] = []
        self.conflicts_remaining = 0
        self.fail_put: Exception | None = None
        self.fail_head_bucket: Exception | None = None

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_calls.append(kwargs)
        if self.fail_put is not None:
            raise self.fail_put
        if self.conflicts_remaining:
            self.conflicts_remaining -= 1
            raise FakeS3Error("ConditionalRequestConflict", 409)
        identity = (kwargs["Bucket"], kwargs["Key"])
        if kwargs["IfNoneMatch"] == "*" and identity in self.objects:
            raise FakeS3Error("PreconditionFailed", 412)
        self.objects[identity] = kwargs["Body"]
        self.metadata[identity] = kwargs["Metadata"]
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        identity = (kwargs["Bucket"], kwargs["Key"])
        if identity not in self.objects:
            raise FakeS3Error("NoSuchKey", 404)
        body = FakeBody(self.objects[identity])
        self.get_bodies.append(body)
        return {
            "Body": body,
            "ContentLength": len(self.objects[identity]),
            "Metadata": self.metadata[identity],
        }

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        identity = (kwargs["Bucket"], kwargs["Key"])
        if identity not in self.objects:
            raise FakeS3Error("NoSuchKey", 404)
        return {
            "ContentLength": len(self.objects[identity]),
            "Metadata": self.metadata[identity],
            "ETag": hashlib.md5(self.objects[identity], usedforsecurity=False).hexdigest(),
        }

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        identity = (kwargs["Bucket"], kwargs["Key"])
        del self.objects[identity]
        del self.metadata[identity]
        return {"ResponseMetadata": {"HTTPStatusCode": 204}}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        prefix = kwargs["Prefix"]
        return {
            "Contents": [
                {
                    "Key": key,
                    "LastModified": __import__("datetime").datetime.now(__import__("datetime").UTC),
                    "Size": len(content),
                    "ETag": hashlib.md5(content, usedforsecurity=False).hexdigest(),
                }
                for (bucket, key), content in self.objects.items()
                if bucket == kwargs["Bucket"] and key.startswith(prefix)
            ],
            "IsTruncated": False,
        }

    def head_bucket(self, **_kwargs: Any) -> dict[str, Any]:
        if self.fail_head_bucket is not None:
            raise self.fail_head_bucket
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}


def build_store(client: FakeS3Client) -> S3ArtifactStore:
    return S3ArtifactStore(client=client, bucket="evalops", prefix="content/v1")


async def test_put_uses_conditional_content_address_and_integrity_metadata() -> None:
    client = FakeS3Client()
    store = build_store(client)
    content = b'{"case_id":"case-1"}\n'
    digest = hashlib.sha256(content).hexdigest()

    stored = await store.put_bytes(content)

    assert stored.sha256 == digest
    assert stored.size_bytes == len(content)
    assert stored.relative_path == Path("content/v1", digest[:2], digest)
    assert stored.created is True
    assert client.put_calls == [
        {
            "Bucket": "evalops",
            "Key": f"content/v1/{digest[:2]}/{digest}",
            "Body": content,
            "ContentLength": len(content),
            "ContentMD5": base64.b64encode(
                hashlib.md5(content, usedforsecurity=False).digest()
            ).decode(),
            "IfNoneMatch": "*",
            "Metadata": {"sha256": digest},
        }
    ]


async def test_duplicate_put_verifies_existing_object_and_reports_not_created() -> None:
    client = FakeS3Client()
    store = build_store(client)
    content = b"same bytes"

    first = await store.put_bytes(content)
    second = await store.put_bytes(content)

    assert first.created is True
    assert second == type(second)(
        sha256=first.sha256,
        size_bytes=first.size_bytes,
        relative_path=first.relative_path,
        created=False,
    )
    assert len(client.objects) == 1


async def test_duplicate_put_rejects_corrupt_existing_object() -> None:
    client = FakeS3Client()
    store = build_store(client)
    content = b"expected"
    digest = hashlib.sha256(content).hexdigest()
    identity = ("evalops", f"content/v1/{digest[:2]}/{digest}")
    client.objects[identity] = b"corrupt"
    client.metadata[identity] = {"sha256": digest}

    with pytest.raises(ArtifactIntegrityError):
        await store.put_bytes(content)


async def test_conflicting_concurrent_publish_is_retried_boundedly() -> None:
    client = FakeS3Client()
    client.conflicts_remaining = 2
    store = build_store(client)

    stored = await store.put_bytes(b"eventual publish")

    assert stored.created is True
    assert len(client.put_calls) == 3


async def test_persistent_concurrent_publish_conflict_fails_closed() -> None:
    client = FakeS3Client()
    client.conflicts_remaining = 3
    store = build_store(client)

    with pytest.raises(ArtifactPublishConflictError):
        await store.put_bytes(b"never published")

    assert len(client.put_calls) == 3


async def test_get_verifies_metadata_content_and_closes_stream() -> None:
    client = FakeS3Client()
    store = build_store(client)
    content = b"verified download"
    stored = await store.put_bytes(content)

    loaded = await store.get_bytes(stored.sha256)

    assert loaded == content
    assert client.get_bodies[-1].closed_by_store is True


async def test_get_rejects_missing_or_corrupt_object() -> None:
    client = FakeS3Client()
    store = build_store(client)
    missing_digest = "0" * 64

    with pytest.raises(ArtifactIntegrityError):
        await store.get_bytes(missing_digest)

    stored = await store.put_bytes(b"original")
    identity = ("evalops", stored.relative_path.as_posix())
    client.objects[identity] = b"tampered"

    with pytest.raises(ArtifactIntegrityError):
        await store.get_bytes(stored.sha256)


async def test_delete_verifies_object_before_removal_and_is_idempotent() -> None:
    client = FakeS3Client()
    store = build_store(client)
    stored = await store.put_bytes(b"delete me")

    assert await store.delete_bytes(stored.sha256) is True
    assert await store.delete_bytes(stored.sha256) is False


async def test_delete_rejects_corrupt_object() -> None:
    client = FakeS3Client()
    store = build_store(client)
    stored = await store.put_bytes(b"do not delete corrupt data")
    identity = ("evalops", stored.relative_path.as_posix())
    client.metadata[identity] = {"sha256": "f" * 64}

    with pytest.raises(ArtifactIntegrityError):
        await store.delete_bytes(stored.sha256)

    assert identity in client.objects


async def test_readiness_uses_bucket_probe_without_writing_an_object() -> None:
    client = FakeS3Client()
    store = build_store(client)

    await store.check_ready()

    assert client.objects == {}


async def test_sync_client_calls_do_not_block_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client()
    store = build_store(client)
    calls: list[tuple[Any, tuple[Any, ...]]] = []

    async def recording_to_thread(function: Any, *args: Any) -> Any:
        calls.append((function, args))
        return function(*args)

    monkeypatch.setattr(asyncio, "to_thread", recording_to_thread)

    await store.put_bytes(b"offloaded")

    assert len(calls) == 1


def test_prefix_rejects_parent_traversal_and_empty_segments() -> None:
    client = FakeS3Client()

    for prefix in ("../content", "/absolute", "content//v1", "content/./v1"):
        with pytest.raises(ValueError, match="prefix"):
            S3ArtifactStore(client=client, bucket="evalops", prefix=prefix)


async def test_identity_delete_rejects_object_replaced_after_scan() -> None:
    client = FakeS3Client()
    store = build_store(client)
    stored = await store.put_bytes(b"scanned")
    expected = (await store.list_objects())[0]
    identity = ("evalops", stored.relative_path.as_posix())
    client.objects[identity] = b"replaced-after-scan"

    with pytest.raises(ArtifactPublishConflictError, match="changed after"):
        await store.delete_object(expected)

    assert client.objects[identity] == b"replaced-after-scan"
