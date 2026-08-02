from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast


def _is_positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _has_no_new_privileges(value: object) -> bool:
    if not isinstance(value, list):
        return False
    normalized = {item.strip().lower().replace("=", ":") for item in value if isinstance(item, str)}
    return bool(
        normalized
        & {
            "no-new-privileges",
            "no-new-privileges:true",
        }
    )


def validate_container_hardening(service: str, inspect_record: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    config_value = inspect_record.get("Config")
    host_config_value = inspect_record.get("HostConfig")
    config = config_value if isinstance(config_value, Mapping) else None
    host_config = host_config_value if isinstance(host_config_value, Mapping) else None

    if config is None:
        errors.append(f"{service}: inspect payload is missing Config")
    if host_config is None:
        errors.append(f"{service}: inspect payload is missing HostConfig")
    if config is None or host_config is None:
        return errors

    raw_user = config.get("User")
    user = raw_user.strip() if isinstance(raw_user, str) else ""
    user_parts = user.lower().split(":", maxsplit=1)
    if not user or user_parts[0] in {"0", "root"}:
        errors.append(f"{service}: effective user must be explicitly non-root, got {user!r}")
    elif len(user_parts) == 2 and user_parts[1] in {"0", "root"}:
        errors.append(f"{service}: effective user must not use the root group, got {user!r}")

    if host_config.get("ReadonlyRootfs") is not True:
        errors.append(f"{service}: root filesystem is not read-only")
    if host_config.get("Privileged") is not False:
        errors.append(f"{service}: privileged mode must be disabled")

    raw_cap_drop = host_config.get("CapDrop")
    cap_drop = (
        {item.upper() for item in raw_cap_drop if isinstance(item, str)}
        if isinstance(raw_cap_drop, list)
        else set()
    )
    if "ALL" not in cap_drop:
        errors.append(f"{service}: effective capability drop set does not include ALL")
    if not _has_no_new_privileges(host_config.get("SecurityOpt")):
        errors.append(f"{service}: no-new-privileges is not enabled")

    resource_fields = (
        ("Memory", "memory"),
        ("NanoCpus", "CPU"),
        ("PidsLimit", "PID"),
    )
    for field, label in resource_fields:
        if not _is_positive_number(host_config.get(field)):
            errors.append(f"{service}: {label} limit is not positive")
    return errors


def _run(command: Sequence[str]) -> str:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}"
            + (f"\n{diagnostic}" if diagnostic else "")
        )
    return completed.stdout


def inspect_compose_service(compose_file: Path, service: str) -> Mapping[str, object]:
    container_output = _run(
        (
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "ps",
            "--quiet",
            service,
        )
    )
    container_ids = [line.strip() for line in container_output.splitlines() if line.strip()]
    if len(container_ids) != 1:
        raise RuntimeError(
            f"{service}: expected exactly one running container, got {len(container_ids)}"
        )

    inspect_output = _run(("docker", "inspect", container_ids[0]))
    try:
        payload = json.loads(inspect_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{service}: docker inspect returned invalid JSON") from exc
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(f"{service}: docker inspect must return exactly one record")
    record = payload[0]
    if not isinstance(record, dict):
        raise RuntimeError(f"{service}: docker inspect record must be an object")
    return cast(Mapping[str, object], record)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail closed unless running Compose containers are hardened."
    )
    parser.add_argument("--compose-file", required=True, type=Path)
    parser.add_argument("services", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors: list[str] = []
    for service in args.services:
        try:
            record = inspect_compose_service(args.compose_file, service)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        errors.extend(validate_container_hardening(service, record))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Verified hardened runtime configuration for: {', '.join(args.services)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
