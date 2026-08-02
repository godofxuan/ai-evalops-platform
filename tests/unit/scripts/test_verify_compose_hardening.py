from scripts.verify_compose_hardening import validate_container_hardening


def _hardened_inspect(*, user: str = "10001:10001") -> dict[str, object]:
    return {
        "Config": {"User": user},
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 536_870_912,
            "NanoCpus": 1_000_000_000,
            "PidsLimit": 256,
        },
    }


def test_validate_container_hardening_accepts_the_complete_runtime_contract() -> None:
    assert validate_container_hardening("api", _hardened_inspect()) == []
    assert validate_container_hardening("postgres", _hardened_inspect(user="postgres")) == []


def test_validate_container_hardening_reports_every_missing_protection() -> None:
    errors = validate_container_hardening(
        "worker",
        {
            "Config": {"User": "root"},
            "HostConfig": {
                "ReadonlyRootfs": False,
                "Privileged": True,
                "CapDrop": None,
                "SecurityOpt": None,
                "Memory": 0,
                "NanoCpus": 0,
                "PidsLimit": 0,
            },
        },
    )

    assert errors == [
        "worker: effective user must be explicitly non-root, got 'root'",
        "worker: root filesystem is not read-only",
        "worker: privileged mode must be disabled",
        "worker: effective capability drop set does not include ALL",
        "worker: no-new-privileges is not enabled",
        "worker: memory limit is not positive",
        "worker: CPU limit is not positive",
        "worker: PID limit is not positive",
    ]


def test_validate_container_hardening_rejects_an_explicit_root_group() -> None:
    errors = validate_container_hardening("api", _hardened_inspect(user="10001:0"))

    assert errors == ["api: effective user must not use the root group, got '10001:0'"]


def test_validate_container_hardening_fails_closed_on_malformed_inspect_data() -> None:
    assert validate_container_hardening("redis", {}) == [
        "redis: inspect payload is missing Config",
        "redis: inspect payload is missing HostConfig",
    ]
