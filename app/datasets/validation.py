import hashlib
import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.datasets.schemas import DatasetCase


@dataclass(frozen=True, slots=True)
class JSONLValidationLimits:
    max_file_bytes: int = 10 * 1024 * 1024
    max_cases: int = 10_000
    max_line_bytes: int = 1024 * 1024


DEFAULT_JSONL_VALIDATION_LIMITS = JSONLValidationLimits()


@dataclass(frozen=True, slots=True)
class ValidatedJSONL:
    content: bytes
    sha256: str
    size_bytes: int
    case_count: int
    cases: tuple[DatasetCase, ...]


class DatasetValidationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        line_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.line_number = line_number


def validate_jsonl(
    content: bytes,
    *,
    limits: JSONLValidationLimits = DEFAULT_JSONL_VALIDATION_LIMITS,
) -> ValidatedJSONL:
    if len(content) > limits.max_file_bytes:
        raise DatasetValidationError(
            "file_too_large",
            f"dataset file exceeds {limits.max_file_bytes} bytes",
        )

    lines = content.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    case_count = len(lines)
    if case_count == 0:
        raise DatasetValidationError("empty_file", "dataset file contains no cases")
    if case_count > limits.max_cases:
        raise DatasetValidationError(
            "too_many_cases",
            f"dataset contains more than {limits.max_cases} cases",
            line_number=limits.max_cases + 1,
        )
    decoded_lines: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            raise DatasetValidationError(
                "blank_line",
                "dataset contains a blank line",
                line_number=line_number,
            )
        if len(raw_line) > limits.max_line_bytes:
            raise DatasetValidationError(
                "line_too_large",
                f"dataset line exceeds {limits.max_line_bytes} bytes",
                line_number=line_number,
            )
        try:
            decoded_lines.append(raw_line.decode("utf-8", errors="strict"))
        except UnicodeDecodeError:
            raise DatasetValidationError(
                "invalid_utf8",
                "dataset line is not valid UTF-8",
                line_number=line_number,
            ) from None
    case_ids: set[str] = set()
    parsed_cases: list[DatasetCase] = []
    for line_number, decoded_line in enumerate(decoded_lines, start=1):
        try:
            record = json.loads(decoded_line)
        except json.JSONDecodeError:
            raise DatasetValidationError(
                "invalid_json",
                "dataset line is not valid JSON",
                line_number=line_number,
            ) from None
        if not isinstance(record, dict):
            raise DatasetValidationError(
                "invalid_record",
                "dataset line must contain a JSON object",
                line_number=line_number,
            )
        try:
            dataset_case = DatasetCase.model_validate(record)
        except ValidationError:
            raise DatasetValidationError(
                "invalid_record",
                "dataset line does not satisfy the required field contract",
                line_number=line_number,
            ) from None
        if dataset_case.case_id in case_ids:
            raise DatasetValidationError(
                "duplicate_case_id",
                "dataset contains a duplicate case_id",
                line_number=line_number,
            )
        case_ids.add(dataset_case.case_id)
        parsed_cases.append(dataset_case)

    return ValidatedJSONL(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        case_count=case_count,
        cases=tuple(parsed_cases),
    )
