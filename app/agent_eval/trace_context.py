"""Safe correlation attributes shared by Agent runtime and EvalOps spans."""

from uuid import UUID


def agent_eval_trace_attributes(
    *,
    session_id: str,
    framework: str,
    run_id: UUID,
    job_id: UUID,
    attempt_id: UUID,
    case_id: str,
    tenant_id: UUID,
) -> dict[str, str]:
    """Return bounded identifiers only; never include prompts, documents, tokens or secrets."""

    return {
        "agent.session_id": session_id,
        "agent.framework": framework,
        "eval.run_id": str(run_id),
        "eval.job_id": str(job_id),
        "eval.attempt_id": str(attempt_id),
        "eval.case_id": case_id,
        "tenant_id": str(tenant_id),
    }
