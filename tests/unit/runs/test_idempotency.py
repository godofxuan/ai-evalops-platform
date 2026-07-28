from app.runs.idempotency import canonical_request_hash


def test_canonical_request_hash_ignores_json_object_key_order() -> None:
    first = {
        "dataset_version_id": "00000000-0000-0000-0000-000000000401",
        "target": {"type": "mock", "config": {"answer": "yes", "latency_ms": 5}},
        "evaluator": {"type": "basic_answer", "config": {"max_attempts": 3}},
    }
    second = {
        "evaluator": {"config": {"max_attempts": 3}, "type": "basic_answer"},
        "target": {"config": {"latency_ms": 5, "answer": "yes"}, "type": "mock"},
        "dataset_version_id": "00000000-0000-0000-0000-000000000401",
    }

    assert canonical_request_hash(first) == canonical_request_hash(second)
