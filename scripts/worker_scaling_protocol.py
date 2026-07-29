from dataclasses import dataclass
from hashlib import sha256

WORKLOADS = ("io_latency_v1", "transient_5pct_v1")
BALANCED_WORKER_ORDERS = (
    (1, 2, 8, 4),
    (2, 4, 1, 8),
    (4, 8, 2, 1),
    (8, 1, 4, 2),
)


@dataclass(frozen=True, slots=True)
class WorkerScalingArm:
    arm_id: str
    workload: str
    repetition: int
    position: int
    workers: int


def build_balanced_arm_plan(*, seed: int = 1729) -> tuple[WorkerScalingArm, ...]:
    arms: list[WorkerScalingArm] = []
    blocks = [
        (workload, repetition, worker_order)
        for workload in WORKLOADS
        for repetition, worker_order in enumerate(BALANCED_WORKER_ORDERS, start=1)
    ]
    blocks.sort(key=lambda block: sha256(f"{seed}:{block[0]}:{block[1]}".encode()).digest())
    for workload, repetition, worker_order in blocks:
        for position, workers in enumerate(worker_order, start=1):
            arms.append(
                WorkerScalingArm(
                    arm_id=f"{workload}-r{repetition:02d}-p{position:02d}-w{workers:02d}",
                    workload=workload,
                    repetition=repetition,
                    position=position,
                    workers=workers,
                )
            )
    return tuple(arms)
