import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    sha256: str
    size_bytes: int
    relative_path: Path
    created: bool


class ArtifactIntegrityError(RuntimeError):
    """The content-addressed path exists but does not contain the expected bytes."""


class ArtifactStore(Protocol):
    async def put_bytes(self, content: bytes) -> StoredArtifact:
        """Persist bytes under a server-derived content address."""

    async def get_bytes(self, sha256: str) -> bytes:
        """Read verified bytes using a server-validated content digest."""


class LocalArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put_bytes(self, content: bytes) -> StoredArtifact:
        return await asyncio.to_thread(self._put_bytes_sync, content)

    async def get_bytes(self, sha256: str) -> bytes:
        return await asyncio.to_thread(self._get_bytes_sync, sha256)

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
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ArtifactIntegrityError("artifact digest is not canonical")
        digest_directory = self._root / sha256[:2]
        if digest_directory.is_symlink():
            raise ArtifactIntegrityError(
                f"artifact digest directory must not be a symlink: {sha256[:2]}"
            )
        path = digest_directory / sha256
        if path.is_symlink() or not path.is_file():
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ArtifactIntegrityError(f"artifact integrity check failed: {sha256}")
        return content

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
