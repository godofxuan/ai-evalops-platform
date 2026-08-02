import argparse
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.auth.api_keys import GeneratedAPIKey
from scripts.create_dev_api_key import build_parser, format_created_key_message
from scripts.revoke_api_key import parse_safe_prefix


def test_created_key_message_contains_plaintext_once_and_never_hash() -> None:
    raw = "evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789"
    generated = GeneratedAPIKey(
        plaintext=SecretStr(raw),
        prefix="evk_001122334455",
        key_hash="scrypt$never-print-this",
    )

    message = format_created_key_message(
        generated,
        tenant_id=UUID("00000000-0000-0000-0000-000000000201"),
        tenant_slug="dev",
    )

    assert message.count(raw) == 1
    assert generated.key_hash not in message
    assert "shown once" in message


def test_revoke_parser_accepts_only_safe_prefix_not_full_secret() -> None:
    assert parse_safe_prefix("evk_001122334455") == "evk_001122334455"

    with pytest.raises(argparse.ArgumentTypeError):
        parse_safe_prefix("evk_001122334455_abcdefghijklmnopqrstuvwxyzABCDEFGH123456789")


def test_create_key_parser_exposes_independent_review_permissions() -> None:
    defaults = build_parser().parse_args(["--tenant-slug", "demo", "--key-name", "ordinary"])
    both = build_parser().parse_args(
        [
            "--tenant-slug",
            "demo",
            "--key-name",
            "review-operator",
            "--human-reviewer",
            "--review-task-creator",
        ]
    )

    assert defaults.human_reviewer is False
    assert defaults.review_task_creator is False
    assert both.human_reviewer is True
    assert both.review_task_creator is True
