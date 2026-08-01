from pathlib import Path

import yaml


def test_http_target_registry_is_documented_and_forwarded_to_services() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")
    compose = yaml.safe_load(Path("deploy/compose.yaml").read_text(encoding="utf-8"))

    assert "EVALOPS_HTTP_TARGET_REGISTRY={}" in env_example
    assert compose["x-app-environment"]["EVALOPS_HTTP_TARGET_REGISTRY"] == (
        "${EVALOPS_HTTP_TARGET_REGISTRY:-{}}"
    )
