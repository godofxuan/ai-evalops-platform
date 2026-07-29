import base64
import binascii
import json
from dataclasses import dataclass
from uuid import UUID

from app.results.schemas import CaseQuery


class InvalidCursorError(ValueError):
    """The cursor is malformed or belongs to another query contract."""


@dataclass(frozen=True, slots=True)
class PagePosition:
    value: str | float | None
    job_id: UUID


class CursorCodec:
    def encode(self, position: PagePosition, *, query: CaseQuery) -> str:
        payload = {
            "v": 1,
            "sort": query.sort,
            "metric": query.metric_name,
            "direction": query.direction,
            "status": None if query.status is None else query.status.value,
            "error_code": query.error_code,
            "value": position.value,
            "job_id": str(position.job_id),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")

    def decode(self, cursor: str, *, query: CaseQuery) -> PagePosition:
        try:
            padding = "=" * (-len(cursor) % 4)
            raw = base64.b64decode(
                cursor + padding,
                altchars=b"-_",
                validate=True,
            )
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise InvalidCursorError
            expected = {
                "v": 1,
                "sort": query.sort,
                "metric": query.metric_name,
                "direction": query.direction,
                "status": None if query.status is None else query.status.value,
                "error_code": query.error_code,
            }
            if any(payload.get(key) != value for key, value in expected.items()):
                raise InvalidCursorError
            value = payload["value"]
            if isinstance(value, bool) or not isinstance(value, (str, int, float, type(None))):
                raise InvalidCursorError
            if query.sort == "case_id" and not isinstance(value, str):
                raise InvalidCursorError
            if (
                query.sort != "case_id"
                and value is not None
                and not isinstance(value, (int, float))
            ):
                raise InvalidCursorError
            job_id = UUID(payload["job_id"])
        except (
            InvalidCursorError,
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            raise InvalidCursorError("cursor is invalid for this query") from None
        return PagePosition(
            value=value if isinstance(value, str) or value is None else float(value),
            job_id=job_id,
        )
