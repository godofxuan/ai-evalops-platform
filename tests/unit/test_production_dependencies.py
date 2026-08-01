import tomllib
from pathlib import Path


def test_http_target_runtime_dependencies_are_installed_without_dev_group() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject["project"]["dependencies"])

    assert "httpx>=0.28.1,<0.29" in dependencies
    assert "httpcore>=1.0.9,<1.1" in dependencies
