from app.observability.metrics import PlatformMetrics
from app.workers.runtime import run_reaper_iteration


class EmptyReaper:
    async def reap(self, *, limit: int = 100) -> tuple[()]:
        assert limit == 17
        return ()


async def test_reaper_iteration_observes_database_operation_duration() -> None:
    metrics = PlatformMetrics()

    reaped = await run_reaper_iteration(EmptyReaper(), metrics=metrics, limit=17)

    assert reaped == ()
    assert 'db_operation_duration_seconds_count{operation="reaper"} 1.0' in metrics.render().decode(
        "utf-8"
    )
