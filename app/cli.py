import argparse
import asyncio
import signal
from collections.abc import Sequence

from app.core.config import Settings
from app.core.event_loop import run_with_psycopg_compatible_event_loop
from app.core.logging import configure_logging, get_logger
from app.workers.runtime import run_reaper_process, run_worker_process


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI EvalOps background process lifecycle")
    parser.add_argument("role", choices=("worker", "reaper"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and exit without starting a long-running process",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one worker/reaper iteration and exit",
    )
    return parser


async def _run_lifecycle(role: str, settings: Settings, *, once: bool) -> None:
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_requested.set)
        except NotImplementedError:
            continue

    if role == "worker":
        await run_worker_process(settings, stop_requested=stop_requested, once=once)
    else:
        await run_reaper_process(settings, stop_requested=stop_requested, once=once)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    settings = Settings()
    configure_logging(log_level=settings.log_level)
    logger = get_logger(__name__)

    if arguments.check:
        logger.info(
            "process_configuration_valid",
            role=arguments.role,
            capability="operational",
        )
        return 0

    run_with_psycopg_compatible_event_loop(
        _run_lifecycle(arguments.role, settings, once=arguments.once)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
