"""Test process paused by a filesystem audit barrier immediately before atomic publication."""

import sys
from multiprocessing.connection import Connection
from pathlib import Path
from threading import Event
from typing import Any

from app.product_experiments.durable_bundle import write_durable_bundle


def run_bundle_crash(payload: bytes, raw: bytes, output: str, barrier: Connection) -> None:
    destination = Path(output)

    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event == "os.rename" and Path(arguments[1]) == destination:
            barrier.send("before_atomic_publish")
            Event().wait()

    sys.addaudithook(audit)
    try:
        write_durable_bundle(payload, output_dir=destination, raw_dataset=raw)
        barrier.send("unexpected_publication")
    except Exception as error:
        barrier.send(("export_error", type(error).__name__))
    finally:
        barrier.close()
