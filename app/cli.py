import argparse
import asyncio
import signal
from collections.abc import Sequence

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI EvalOps background process lifecycle")
    parser.add_argument("role", choices=("worker", "reaper"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and exit without starting a long-running process",
    )
    return parser


async def _run_lifecycle(role: str) -> None:
    logger = get_logger(__name__, role=role, capability="lifecycle_only")
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(shutdown_signal, stop_requested.set)
        except NotImplementedError:
            continue

    logger.info("process_scaffold_started")
    await stop_requested.wait()
    logger.info("process_scaffold_stopped")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    settings = Settings()
    configure_logging(log_level=settings.log_level)
    logger = get_logger(__name__)

    if arguments.check:
        logger.info(
            "process_configuration_valid",
            role=arguments.role,
            capability="lifecycle_only",
        )
        return 0

    asyncio.run(_run_lifecycle(arguments.role))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
