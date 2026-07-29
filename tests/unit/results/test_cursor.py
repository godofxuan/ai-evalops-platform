from uuid import UUID

import pytest

from app.results.cursor import CursorCodec, InvalidCursorError, PagePosition
from app.results.schemas import CaseQuery

JOB_ID = UUID("00000000-0000-0000-0000-000000000701")


def test_cursor_round_trips_and_cannot_be_reused_with_another_sort_contract() -> None:
    codec = CursorCodec()
    query = CaseQuery(
        sort="metric",
        metric_name="lexical_f1",
        direction="desc",
    )
    cursor = codec.encode(PagePosition(value=0.75, job_id=JOB_ID), query=query)

    assert codec.decode(cursor, query=query) == PagePosition(value=0.75, job_id=JOB_ID)

    with pytest.raises(InvalidCursorError):
        codec.decode(
            cursor,
            query=CaseQuery(
                sort="metric",
                metric_name="lexical_recall",
                direction="desc",
            ),
        )
