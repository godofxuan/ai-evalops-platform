"""Fail closed when benchmark behavior differs from a locked Git revision."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import PurePosixPath

BEHAVIORAL_DIRECTORY_PREFIXES = ("app/", "scripts/", "alembic/", "deploy/")
BEHAVIORAL_ROOT_FILES = frozenset(
    {".python-version", "alembic.ini", "pyproject.toml", "uv.lock"}
)


def _is_repository_relative_posix_path(path: str) -> bool:
    if not path or "\\" in path:
        return False
    candidate = PurePosixPath(path)
    return (
        not candidate.is_absolute()
        and ".." not in candidate.parts
        and "." not in candidate.parts
    )


def behavioral_source_lock_violations(paths: Iterable[str]) -> tuple[str, ...]:
    """Return behavioral or malformed changed paths in deterministic order."""
    violations: set[str] = set()
    for raw_path in paths:
        path = raw_path.strip()
        if not _is_repository_relative_posix_path(path):
            violations.add(raw_path)
            continue
        if path in BEHAVIORAL_ROOT_FILES or path.startswith(BEHAVIORAL_DIRECTORY_PREFIXES):
            violations.add(path)
    return tuple(sorted(violations))


def changed_paths(*, locked_sha: str, head: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{locked_sha}..{head}", "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in result.stdout.splitlines() if line)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locked-sha", required=True)
    parser.add_argument("--head", default="HEAD")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        violations = behavioral_source_lock_violations(
            changed_paths(locked_sha=args.locked_sha, head=args.head)
        )
    except subprocess.CalledProcessError as exc:
        print(f"behavioral source lock could not inspect Git history: {exc}", file=sys.stderr)
        return 2
    if violations:
        print("behavioral source lock violation:", file=sys.stderr)
        for path in violations:
            print(f"- {path}", file=sys.stderr)
        return 1
    print(f"behavioral source lock valid: {args.locked_sha}..{args.head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
