"""Inspect Tasks used for deterministic CI interop and external harness execution."""

from __future__ import annotations

from typing import cast

from inspect_ai import Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, Solver, TaskState, solver


@solver
def deterministic_harness_solver(answer: str) -> Solver:
    """Model-free solver: this validates framework plumbing, not model quality."""

    async def solve(state: TaskState, _generate: Generate) -> TaskState:
        state.output = ModelOutput.from_content(
            model="evalops/deterministic-harness",
            content=answer,
        )
        state.completed = True
        return state

    return cast(Solver, solve)


def build_mechanism_smoke_task() -> Task:
    answer = "deterministic harness answer"
    return Task(
        dataset=MemoryDataset(
            samples=[
                Sample(
                    id="inspect-mechanism-smoke",
                    input="Return the deterministic harness answer.",
                    target=answer,
                    metadata={"evidence_class": "mechanism_ci"},
                )
            ],
            name="external_harness_mechanism_smoke_v1",
        ),
        solver=deterministic_harness_solver(answer),
        scorer=match(),
    )


__all__ = ["build_mechanism_smoke_task", "deterministic_harness_solver"]
