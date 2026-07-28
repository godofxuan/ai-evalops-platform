import hashlib
import json

import pytest

from app.datasets.validation import (
    DatasetValidationError,
    JSONLValidationLimits,
    validate_jsonl,
)


def encode_line(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_validate_jsonl_accepts_required_fields_and_preserves_content() -> None:
    first = {
        "case_id": "case-1",
        "question": "二加二是多少？",
        "expected_answer": "4",
        "metadata": {"language": "zh-CN"},
        "custom_field": ["extra", 1],
    }
    second = {
        "case_id": "case-2",
        "question": "capital of France?",
        "expected_answer": None,
        "metadata": {},
    }
    content = encode_line(first) + b"\n" + encode_line(second) + b"\n"

    validated = validate_jsonl(content)

    assert validated.content == content
    assert validated.sha256 == hashlib.sha256(content).hexdigest()
    assert validated.size_bytes == len(content)
    assert validated.case_count == 2


def test_validate_jsonl_rejects_file_larger_than_limit() -> None:
    content = encode_line(
        {
            "case_id": "case-1",
            "question": "q",
            "expected_answer": "a",
            "metadata": {},
        }
    )
    limits = JSONLValidationLimits(
        max_file_bytes=len(content) - 1,
        max_cases=10,
        max_line_bytes=len(content),
    )

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content, limits=limits)

    assert captured.value.code == "file_too_large"
    assert captured.value.line_number is None


def test_validate_jsonl_rejects_more_cases_than_limit() -> None:
    record = {
        "case_id": "case-1",
        "question": "q",
        "expected_answer": "a",
        "metadata": {},
    }
    content = encode_line(record) + b"\n" + encode_line(record | {"case_id": "case-2"})
    limits = JSONLValidationLimits(
        max_file_bytes=len(content),
        max_cases=1,
        max_line_bytes=len(content),
    )

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content, limits=limits)

    assert captured.value.code == "too_many_cases"
    assert captured.value.line_number == 2


def test_validate_jsonl_rejects_line_larger_than_limit() -> None:
    content = encode_line(
        {
            "case_id": "case-1",
            "question": "long question",
            "expected_answer": "a",
            "metadata": {},
        }
    )
    limits = JSONLValidationLimits(
        max_file_bytes=len(content),
        max_cases=1,
        max_line_bytes=len(content) - 1,
    )

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content, limits=limits)

    assert captured.value.code == "line_too_large"
    assert captured.value.line_number == 1


def test_validate_jsonl_rejects_blank_line_but_allows_final_newline() -> None:
    first = encode_line(
        {
            "case_id": "case-1",
            "question": "q1",
            "expected_answer": "a1",
            "metadata": {},
        }
    )
    second = encode_line(
        {
            "case_id": "case-2",
            "question": "q2",
            "expected_answer": "a2",
            "metadata": {},
        }
    )
    content = first + b"\n\n" + second + b"\n"

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content)

    assert captured.value.code == "blank_line"
    assert captured.value.line_number == 2


def test_validate_jsonl_rejects_empty_file() -> None:
    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(b"")

    assert captured.value.code == "empty_file"
    assert captured.value.line_number is None


def test_validate_jsonl_rejects_non_utf8_line_with_location() -> None:
    content = (
        b'{"case_id":"case-1","question":"q","expected_answer":"a","metadata":{}}\n'
        b'{"case_id":"case-2","question":"\xff","expected_answer":"a","metadata":{}}'
    )

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content)

    assert captured.value.code == "invalid_utf8"
    assert captured.value.line_number == 2


def test_validate_jsonl_rejects_invalid_json_with_location() -> None:
    content = (
        b'{"case_id":"case-1","question":"q","expected_answer":"a","metadata":{}}\n{"case_id":'
    )

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content)

    assert captured.value.code == "invalid_json"
    assert captured.value.line_number == 2


def test_validate_jsonl_requires_each_line_to_be_an_object() -> None:
    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(b"[]")

    assert captured.value.code == "invalid_record"
    assert captured.value.line_number == 1


@pytest.mark.parametrize(
    "record",
    [
        {
            "question": "q",
            "expected_answer": "a",
            "metadata": {},
        },
        {
            "case_id": "   ",
            "question": "q",
            "expected_answer": "a",
            "metadata": {},
        },
        {
            "case_id": 1,
            "question": "q",
            "expected_answer": "a",
            "metadata": {},
        },
        {
            "case_id": "case-1",
            "expected_answer": "a",
            "metadata": {},
        },
        {
            "case_id": "case-1",
            "question": "",
            "expected_answer": "a",
            "metadata": {},
        },
        {
            "case_id": "case-1",
            "question": 1,
            "expected_answer": "a",
            "metadata": {},
        },
        {
            "case_id": "case-1",
            "question": "q",
            "metadata": {},
        },
        {
            "case_id": "case-1",
            "question": "q",
            "expected_answer": "a",
        },
        {
            "case_id": "case-1",
            "question": "q",
            "expected_answer": "a",
            "metadata": [],
        },
    ],
    ids=[
        "missing-case-id",
        "blank-case-id",
        "non-string-case-id",
        "missing-question",
        "blank-question",
        "non-string-question",
        "missing-expected-answer",
        "missing-metadata",
        "non-object-metadata",
    ],
)
def test_validate_jsonl_enforces_required_record_fields(record: object) -> None:
    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(encode_line(record))

    assert captured.value.code == "invalid_record"
    assert captured.value.line_number == 1


def test_validate_jsonl_rejects_duplicate_case_id_with_location() -> None:
    record = {
        "case_id": "duplicate",
        "question": "q",
        "expected_answer": "a",
        "metadata": {},
    }
    content = encode_line(record) + b"\n" + encode_line(record | {"question": "another"})

    with pytest.raises(DatasetValidationError) as captured:
        validate_jsonl(content)

    assert captured.value.code == "duplicate_case_id"
    assert captured.value.line_number == 2
