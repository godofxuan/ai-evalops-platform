import hashlib
import json

from app.datasets.validation import validate_jsonl


def test_product_dataset_maps_to_core_without_reusing_raw_digest() -> None:
    from app.product_experiments.dataset_mapping import map_product_dataset

    cases = [
        {
            "case_id": f"q-{index}",
            "category": "safe",
            "prompt": "question",
            "reference_answer": "private gold",
            "allowed_tools": [],
            "max_tool_calls": 0,
            "metadata": {"public_context": {"locale": "zh"}},
        }
        for index in range(2)
    ]
    original = json.dumps(cases).encode()
    digest = hashlib.sha256(original).hexdigest()
    mapped = map_product_dataset(original, expected_sha256=digest)
    assert mapped.source_sha256 == digest
    assert mapped.mapping_version == "evalops.product-dataset-mapping/1.0"
    assert mapped.dataset.sha256 != digest
    validated = validate_jsonl(mapped.dataset.content)
    assert validated.sha256 == mapped.dataset.sha256
    case = validated.cases[0]
    assert case.question == "question" and case.expected_answer == "private gold"
    assert case.metadata["public_context"] == {"locale": "zh"}
    assert case.metadata["evalops_product_case"]["allowed_tools"] == []
    assert case.metadata["evalops_product_case"]["max_tool_calls"] == 0
