import asyncio
import base64
import hashlib
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import boto3
from botocore.config import Config

from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    sha256: str
    size_bytes: int
    relative_path: Path
    created: bool


@dataclass(frozen=True, slots=True)
class StoredObjectInfo:
    sha256: str
    last_modified: datetime


class ArtifactIntegrityError(RuntimeError):
    """The content-addressed path exists but does not contain the expected bytes."""


class ArtifactPublishConflictError(RuntimeError):
    """Concurrent object publication did not settle within the bounded retry limit."""


class S3Client(Protocol):
    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]: ...

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...


class ArtifactStore(Protocol):
    async def put_bytes(self, content: bytes) -> StoredArtifact:
        """Persist bytes under a server-derived content address."""

    async def get_bytes(self, sha256: str) -> bytes:
        """Read verified bytes using a server-validated content digest."""

    async def check_ready(self) -> None:
        """Verify that the configured storage dependency can be reached."""


class DeletableArtifactStore(ArtifactStore, Protocol):
    async def delete_bytes(self, sha256: str) -> bool:
        """Delete a verified content address, returning whether it existed."""

    async def list_objects(self) -> list[StoredObjectInfo]:
        """List content-addressed objects with storage modification time."""


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put_bytes(self, content: bytes) -> StoredArtifact:
        return await asyncio.to_thread(self._put_bytes_sync, content)

    async def get_bytes(self, sha256: str) -> bytes:
        return await asyncio.to_thread(self._get_bytes_sync, sha256)

    async def delete_bytes(self, sha256: str) -> bool:
        return await asyncio.to_thread(self._delete_bytes_sync, sha256)

    async def check_ready(self) -> None:
        await asyncio.to_thread(self._check_ready_sync)

    async def list_objects(self) -> list[StoredObjectInfo]:
        return await asyncio.to_thread(self._list_objects_sync)

    def _put_bytes_sync(self, content: bytes) -> StoredArtifact:
        digest = hashlib.sha256(content).hexdigest()
        relative_path = Path(digest[:2], digest)
        destination = self._root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.parent.is_symlink():
            raise ArtifactIntegrityError(
                f"artifact digest directory must not be a symlink: {digest[:2]}"
            )

        if destination.exists() or destination.is_symlink():
            self._assert_artifact_file(
                destination,
                expected_sha256=digest,
                expected_size=len(content),
            )
            return StoredArtifact(
                sha256=digest,
                size_bytes=len(content),
                relative_path=relative_path,
                created=False,
            )

        temporary_path: Path | None = None
        created = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{digest}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            self._assert_artifact_file(
                temporary_path,
                expected_sha256=digest,
                expected_size=len(content),
            )
            try:
                os.link(temporary_path, destination)
                created = True
            except FileExistsError:
                self._assert_artifact_file(
                    destination,
                    expected_sha256=digest,
                    expected_size=len(content),
                )
                created = False

            return StoredArtifact(
                sha256=digest,
                size_bytes=len(content),
                relative_path=relative_path,
                created=created,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _get_bytes_sync(self, sha256: str) -> bytes:
        path = self._artifact_path(sha256)
        if path.is_symlink() or not path.is_file():
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        return content

    def _delete_bytes_sync(self, sha256: str) -> bool:
        path = self._artifact_path(sha256)
        if path.is_symlink():
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        if not path.exists():
            return False
        self._assert_artifact_file(
            path,
            expected_sha256=sha256,
            expected_size=path.stat().st_size,
        )
        path.unlink()
        with suppress(OSError):
            path.parent.rmdir()
        return True

    def _artifact_path(self, sha256: str) -> Path:
        _validate_digest(sha256)
        digest_directory = self._root / sha256[:2]
        if digest_directory.is_symlink():
            raise ArtifactIntegrityError(
                f"artifact digest directory must not be a symlink: {sha256[:2]}"
            )
        return digest_directory / sha256

    @staticmethod
    def _assert_artifact_file(
        path: Path,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> None:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {expected_sha256}")

        with path.open("rb") as artifact_file:
            actual_sha256 = hashlib.file_digest(artifact_file, "sha256").hexdigest()
        if actual_sha256 != expected_sha256:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {expected_sha256}")

    def _check_ready_sync(self) -> None:
        if not self._root.is_dir():
            raise ArtifactIntegrityError("artifact root is unavailable")

        probe_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=".readiness-",
                delete=False,
            ) as probe_file:
                probe_path = Path(probe_file.name)
                probe_file.write(b"ready")
                probe_file.flush()
                os.fsync(probe_file.fileno())
        finally:
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)

    def _list_objects_sync(self) -> list[StoredObjectInfo]:
        if not self._root.exists():
            return []
        objects: list[StoredObjectInfo] = []
        for path in self._root.glob("[0-9a-f][0-9a-f]/*"):
            if not path.is_file():
                continue
            try:
                _validate_digest(path.name)
            except ArtifactIntegrityError:
                continue
            objects.append(
                StoredObjectInfo(
                    sha256=path.name,
                    last_modified=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                )
            )
        return sorted(objects, key=lambda item: item.sha256)


class S3ArtifactStore:
    _MAX_PUBLISH_ATTEMPTS = 3

    def __init__(self, *, client: S3Client, bucket: str, prefix: str = "artifacts/v1") -> None:
        if not bucket.strip():
            raise ValueError("artifact S3 bucket must not be empty")
        self._client = client
        self._bucket = bucket
        self._prefix = _validate_s3_prefix(prefix)

    async def put_bytes(self, content: bytes) -> StoredArtifact:
        return await asyncio.to_thread(self._put_bytes_sync, content)

    async def get_bytes(self, sha256: str) -> bytes:
        return await asyncio.to_thread(self._get_bytes_sync, sha256)

    async def delete_bytes(self, sha256: str) -> bool:
        return await asyncio.to_thread(self._delete_bytes_sync, sha256)

    async def check_ready(self) -> None:
        await asyncio.to_thread(self._check_ready_sync)

    async def list_objects(self) -> list[StoredObjectInfo]:
        return await asyncio.to_thread(self._list_objects_sync)

    def _put_bytes_sync(self, content: bytes) -> StoredArtifact:
        digest = hashlib.sha256(content).hexdigest()
        relative_path = self._relative_path(digest)
        key = relative_path.as_posix()
        content_md5 = base64.b64encode(hashlib.md5(content, usedforsecurity=False).digest()).decode(
            "ascii"
        )
        last_conflict: Exception | None = None

        for _attempt in range(self._MAX_PUBLISH_ATTEMPTS):
            try:
                self._client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=content,
                    ContentLength=len(content),
                    ContentMD5=content_md5,
                    IfNoneMatch="*",
                    Metadata={"sha256": digest},
                )
            except Exception as error:
                status_code, error_code = _s3_error_identity(error)
                if status_code == 412 or error_code == "PreconditionFailed":
                    existing = self._get_bytes_sync(digest)
                    if existing != content:
                        raise ArtifactIntegrityError(
                            f"artifact integrity check failed: {digest}"
                        ) from error
                    return StoredArtifact(
                        sha256=digest,
                        size_bytes=len(content),
                        relative_path=relative_path,
                        created=False,
                    )
                if status_code == 409 or error_code == "ConditionalRequestConflict":
                    last_conflict = error
                    continue
                raise
            return StoredArtifact(
                sha256=digest,
                size_bytes=len(content),
                relative_path=relative_path,
                created=True,
            )

        raise ArtifactPublishConflictError(
            f"artifact publish conflict did not settle: {digest}"
        ) from last_conflict

    def _get_bytes_sync(self, sha256: str) -> bytes:
        key = self._relative_path(sha256).as_posix()
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as error:
            if _is_s3_missing(error):
                raise ArtifactIntegrityError(
                    f"artifact integrity check failed: {sha256}"
                ) from error
            raise

        body = response.get("Body")
        if body is None or not hasattr(body, "read") or not hasattr(body, "close"):
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        try:
            content = cast(bytes, body.read())
        finally:
            body.close()
        self._assert_object(
            content,
            expected_sha256=sha256,
            content_length=response.get("ContentLength"),
            metadata=response.get("Metadata"),
        )
        return content

    def _delete_bytes_sync(self, sha256: str) -> bool:
        key = self._relative_path(sha256).as_posix()
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as error:
            if _is_s3_missing(error):
                return False
            raise
        if response.get("ContentLength") is None or response.get("Metadata") != {"sha256": sha256}:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        content = self._get_bytes_sync(sha256)
        if len(content) != response["ContentLength"]:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

    def _check_ready_sync(self) -> None:
        self._client.head_bucket(Bucket=self._bucket)

    def _list_objects_sync(self) -> list[StoredObjectInfo]:
        prefix = f"{self._prefix}/"
        token: str | None = None
        objects: list[StoredObjectInfo] = []
        while True:
            arguments: dict[str, object] = {"Bucket": self._bucket, "Prefix": prefix}
            if token is not None:
                arguments["ContinuationToken"] = token
            response = self._client.list_objects_v2(**arguments)
            contents = response.get("Contents", [])
            if isinstance(contents, list):
                for item in contents:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("Key")
                    modified = item.get("LastModified")
                    if not isinstance(key, str) or not isinstance(modified, datetime):
                        continue
                    digest = key.rsplit("/", 1)[-1]
                    try:
                        _validate_digest(digest)
                    except ArtifactIntegrityError:
                        continue
                    objects.append(StoredObjectInfo(digest, modified))
            if not response.get("IsTruncated"):
                break
            next_token = response.get("NextContinuationToken")
            if not isinstance(next_token, str):
                raise ArtifactIntegrityError("truncated S3 listing omitted continuation token")
            token = next_token
        return sorted(objects, key=lambda item: item.sha256)

    def _relative_path(self, sha256: str) -> Path:
        _validate_digest(sha256)
        return Path(*self._prefix.split("/"), sha256[:2], sha256)

    @staticmethod
    def _assert_object(
        content: bytes,
        *,
        expected_sha256: str,
        content_length: object,
        metadata: object,
    ) -> None:
        if content_length != len(content) or metadata != {"sha256": expected_sha256}:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {expected_sha256}")
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {expected_sha256}")


def _validate_digest(sha256: str) -> None:
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise ArtifactIntegrityError("artifact digest is not canonical")


def _validate_s3_prefix(prefix: str) -> str:
    segments = prefix.split("/")
    if (
        not prefix
        or prefix.startswith("/")
        or any(segment in {"", ".", ".."} for segment in segments)
    ):
        raise ValueError("artifact S3 prefix must be a non-empty relative key prefix")
    return prefix


def _s3_error_identity(error: Exception) -> tuple[int | None, str | None]:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None, None
    metadata = response.get("ResponseMetadata")
    error_body = response.get("Error")
    status_code = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
    error_code = error_body.get("Code") if isinstance(error_body, dict) else None
    return (
        status_code if isinstance(status_code, int) else None,
        error_code if isinstance(error_code, str) else None,
    )


def _is_s3_missing(error: Exception) -> bool:
    status_code, error_code = _s3_error_identity(error)
    return status_code == 404 or error_code in {"404", "NoSuchKey", "NotFound"}


def build_artifact_store(settings: Settings) -> ArtifactStore:
    if settings.artifact_backend == "local":
        settings.artifact_root.mkdir(parents=True, exist_ok=True)
        return LocalArtifactStore(settings.artifact_root)

    if settings.artifact_s3_bucket is None:
        raise ValueError("artifact S3 bucket is required for the S3 backend")
    access_key = (
        None
        if settings.artifact_s3_access_key_id is None
        else settings.artifact_s3_access_key_id.get_secret_value()
    )
    secret_key = (
        None
        if settings.artifact_s3_secret_access_key is None
        else settings.artifact_s3_secret_access_key.get_secret_value()
    )
    client = cast(
        S3Client,
        boto3.client(
            "s3",
            endpoint_url=settings.artifact_s3_endpoint_url,
            region_name=settings.artifact_s3_region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                s3={"addressing_style": settings.artifact_s3_addressing_style},
                retries={"mode": "standard", "max_attempts": 3},
            ),
        ),
    )
    return S3ArtifactStore(
        client=client,
        bucket=settings.artifact_s3_bucket,
        prefix=settings.artifact_s3_prefix,
    )
