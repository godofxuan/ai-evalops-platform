import asyncio
import hashlib
from pathlib import Path

import pytest

from app.artifacts.storage import ArtifactIntegrityError, LocalArtifactStore


def list_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


async def test_put_bytes_uses_server_computed_content_address(tmp_path: Path) -> None:
    content = b'{"case_id":"case-1"}\n'
    expected_sha256 = hashlib.sha256(content).hexdigest()
    store = LocalArtifactStore(tmp_path)

    stored = await store.put_bytes(content)

    assert stored.sha256 == expected_sha256
    assert stored.size_bytes == len(content)
    assert stored.relative_path == Path(expected_sha256[:2], expected_sha256)
    assert stored.created is True
    assert (tmp_path / stored.relative_path).read_bytes() == content


async def test_put_bytes_reuses_existing_physical_artifact(tmp_path: Path) -> None:
    content = b'{"case_id":"case-1"}\n'
    store = LocalArtifactStore(tmp_path)
    first = await store.put_bytes(content)
    artifact_path = tmp_path / first.relative_path
    first_modified_ns = artifact_path.stat().st_mtime_ns

    second = await store.put_bytes(content)

    assert second == type(second)(
        sha256=first.sha256,
        size_bytes=first.size_bytes,
        relative_path=first.relative_path,
        created=False,
    )
    assert artifact_path.stat().st_mtime_ns == first_modified_ns
    assert await asyncio.to_thread(list_files, tmp_path) == [artifact_path]


async def test_put_bytes_rejects_corrupt_existing_content_address(tmp_path: Path) -> None:
    content = b'{"case_id":"case-1"}\n'
    digest = hashlib.sha256(content).hexdigest()
    artifact_path = tmp_path / digest[:2] / digest
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"corrupt")
    store = LocalArtifactStore(tmp_path)

    with pytest.raises(ArtifactIntegrityError):
        await store.put_bytes(content)


async def test_put_bytes_cleans_temporary_file_when_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalArtifactStore(tmp_path)

    def fail_publish(_source: object, _destination: object) -> None:
        raise OSError("simulated publish failure")

    monkeypatch.setattr("app.artifacts.storage.os.link", fail_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        await store.put_bytes(b'{"case_id":"case-1"}\n')

    assert await asyncio.to_thread(list_files, tmp_path) == []


async def test_put_bytes_verifies_temporary_content_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalArtifactStore(tmp_path)

    class WrongDigest:
        @staticmethod
        def hexdigest() -> str:
            return "0" * 64

    monkeypatch.setattr(
        "app.artifacts.storage.hashlib.file_digest",
        lambda *_args, **_kwargs: WrongDigest(),
    )

    with pytest.raises(ArtifactIntegrityError):
        await store.put_bytes(b'{"case_id":"case-1"}\n')

    assert await asyncio.to_thread(list_files, tmp_path) == []


async def test_put_bytes_rejects_symlinked_digest_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b'{"case_id":"case-1"}\n'
    digest = hashlib.sha256(content).hexdigest()
    digest_directory = await asyncio.to_thread(tmp_path.resolve) / digest[:2]
    original_is_symlink = Path.is_symlink

    def report_digest_directory_as_symlink(path: Path) -> bool:
        if path == digest_directory:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_digest_directory_as_symlink)
    store = LocalArtifactStore(tmp_path)

    with pytest.raises(ArtifactIntegrityError):
        await store.put_bytes(content)

    assert await asyncio.to_thread(list_files, tmp_path) == []
