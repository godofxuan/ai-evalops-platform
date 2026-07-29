from scripts.gate1_preflight import evaluate_preflight, required_services_healthy


def test_preflight_reports_every_blocker_without_secret_values() -> None:
    result = evaluate_preflight(
        {
            "source_commit_matches": True,
            "tracked_worktree_clean": True,
            "docker_cli_available": False,
            "compose_config_valid": False,
            "required_services_healthy": False,
            "disk_space_sufficient": True,
            "api_key_present": True,
            "database_url_present": False,
            "quality_gate_confirmed": True,
            "adoption_gate_confirmed": False,
        }
    )

    assert result["ready"] is False
    assert result["blockers"] == [
        "docker_cli_available",
        "compose_config_valid",
        "required_services_healthy",
        "database_url_present",
        "adoption_gate_confirmed",
    ]
    assert "secret" not in str(result).lower()


def test_compose_service_health_requires_core_health_and_running_workers() -> None:
    services = [
        {"Service": "postgres", "State": "running", "Health": "healthy"},
        {"Service": "redis", "State": "running", "Health": "healthy"},
        {"Service": "api", "State": "running", "Health": "healthy"},
        {"Service": "reaper", "State": "running", "Health": ""},
        {"Service": "worker", "State": "running", "Health": ""},
        {"Service": "worker", "State": "running", "Health": ""},
    ]

    assert required_services_healthy(services) is True
    services[2]["Health"] = "starting"
    assert required_services_healthy(services) is False
