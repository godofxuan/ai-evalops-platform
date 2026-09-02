from __future__ import annotations

from collections import Counter

from scripts.build_agent_tool_demo_dataset import CATEGORIES, build_cases, encoded_cases


def test_agent_tool_demo_is_deterministic_balanced_and_contains_failure_modes() -> None:
    cases = build_cases()

    assert len(cases) == 120
    assert Counter(case["category"] for case in cases) == {name: 20 for name in CATEGORIES}
    assert encoded_cases() == encoded_cases()
    authorization = next(case for case in cases if case["category"] == "authorization")
    budget = next(case for case in cases if case["category"] == "budget")
    recovery = next(case for case in cases if case["category"] == "recovery")
    assert (
        authorization["metadata"]["fixture_profiles"]["baseline"]["tool_calls"][0]["name"]
        == "admin_delete"
    )
    assert budget["metadata"]["fixture_profiles"]["baseline"]["budget_exhausted"] is True
    assert recovery["metadata"]["fixture_profiles"]["baseline"]["terminal_state"] == "failed"
