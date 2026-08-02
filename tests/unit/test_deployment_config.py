from pathlib import Path
from typing import Any

import yaml

APP_SERVICES = ("migrate", "api", "worker", "reaper")
STATEFUL_SERVICES = ("postgres", "redis")
ALL_SERVICES = (*STATEFUL_SERVICES, *APP_SERVICES)


def _load_compose() -> dict[str, Any]:
    loaded = yaml.safe_load(Path("deploy/compose.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_http_target_registry_is_documented_and_forwarded_to_services() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    compose = _load_compose()

    assert "EVALOPS_HTTP_TARGET_REGISTRY={}" in env_example
    assert compose["x-app-environment"]["EVALOPS_HTTP_TARGET_REGISTRY"] == (
        "${EVALOPS_HTTP_TARGET_REGISTRY:-{}}"
    )


def test_every_compose_service_has_an_explicit_non_root_user() -> None:
    services = _load_compose()["services"]

    expected_users = {
        "postgres": "postgres",
        "redis": "redis",
        "migrate": "10001:10001",
        "api": "10001:10001",
        "worker": "10001:10001",
        "reaper": "10001:10001",
    }
    assert {name: services[name].get("user") for name in ALL_SERVICES} == expected_users


def test_every_compose_service_drops_privilege_and_uses_a_read_only_rootfs() -> None:
    services = _load_compose()["services"]

    for name in ALL_SERVICES:
        service = services[name]
        assert service.get("read_only") is True, name
        assert service.get("cap_drop") == ["ALL"], name
        assert service.get("security_opt") == ["no-new-privileges:true"], name


def test_every_compose_service_has_cpu_memory_and_pid_limits() -> None:
    compose = _load_compose()
    services = compose["services"]
    env_example = Path(".env.example").read_text(encoding="utf-8")

    for name in ALL_SERVICES:
        service = services[name]
        assert service.get("cpus"), name
        assert service.get("mem_limit"), name
        assert service.get("pids_limit"), name

    for variable in (
        "EVALOPS_APP_CPUS",
        "EVALOPS_APP_MEMORY_LIMIT",
        "EVALOPS_APP_PIDS_LIMIT",
        "EVALOPS_POSTGRES_CPUS",
        "EVALOPS_POSTGRES_MEMORY_LIMIT",
        "EVALOPS_POSTGRES_PIDS_LIMIT",
        "EVALOPS_REDIS_CPUS",
        "EVALOPS_REDIS_MEMORY_LIMIT",
        "EVALOPS_REDIS_PIDS_LIMIT",
    ):
        assert f"{variable}=" in env_example


def test_read_only_services_declare_only_their_required_writable_paths() -> None:
    services = _load_compose()["services"]

    for name in APP_SERVICES:
        assert "/tmp:size=64m,mode=1777" in services[name].get("tmpfs", []), name

    assert services["postgres"]["tmpfs"] == [
        "/tmp:size=64m,mode=1777",
        "/var/run/postgresql:size=16m,mode=3777",
    ]
    assert services["redis"]["tmpfs"] == ["/tmp:size=64m,mode=1777"]

    assert services["postgres"]["volumes"] == ["postgres_data:/var/lib/postgresql"]
    assert services["redis"]["volumes"] == ["redis_data:/data"]
    assert services["api"]["volumes"] == ["artifact_data:/data/artifacts"]
    assert services["worker"]["volumes"] == ["artifact_data:/data/artifacts"]
    assert "volumes" not in services["migrate"]
    assert "volumes" not in services["reaper"]


def test_compose_smoke_verifies_effective_runtime_hardening() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["compose-smoke"]["steps"]
    matching_steps = [
        step for step in steps if step.get("name") == "Verify effective container hardening"
    ]

    assert len(matching_steps) == 1
    command = matching_steps[0]["run"]
    assert "python3 scripts/verify_compose_hardening.py" in command
    assert "postgres redis api worker reaper" in command


def test_outbox_alert_rules_cover_stalled_backlog_and_lease_loss() -> None:
    rules_path = Path("deploy/prometheus/outbox-alerts.yml")
    loaded = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    groups = loaded["groups"]
    assert len(groups) == 1
    assert groups[0]["name"] == "ai-evalops-outbox"
    rules = {rule["alert"]: rule for rule in groups[0]["rules"]}

    assert rules["AIEvalOpsOutboxDeliveryStalled"] == {
        "alert": "AIEvalOpsOutboxDeliveryStalled",
        "expr": "outbox_pending > 0 and outbox_oldest_pending_age_seconds > 300",
        "for": "10m",
        "labels": {"severity": "warning"},
        "annotations": {
            "summary": "AI EvalOps Outbox delivery is stalled",
            "description": "The oldest unpublished progress event has remained pending.",
        },
    }
    assert rules["AIEvalOpsOutboxLeaseLoss"]["expr"] == (
        "increase(outbox_lease_lost_total[10m]) > 0"
    )
    assert rules["AIEvalOpsOutboxLeaseLoss"]["for"] == "5m"
    serialized = rules_path.read_text(encoding="utf-8")
    assert "tenant_id" not in serialized
    assert "run_id" not in serialized
    assert "event_id" not in serialized
