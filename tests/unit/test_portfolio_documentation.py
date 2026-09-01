import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CURRENT_DOCUMENTS = (
    "README.md",
    "PROJECT_STATUS.md",
    "docs/handoffs/PROJECT_EVIDENCE_MAP.md",
    "docs/handoffs/CROSS_SURFACE_CONSISTENCY.md",
    "docs/handoffs/RESUME_CODEX_HANDOFF.md",
    "docs/handoffs/RESUME_METRIC_LEDGER.md",
    "docs/handoffs/RESUME_INTERVIEW_CONSISTENCY.md",
    "docs/handoffs/TEACHING_CODEX_HANDOFF.md",
    "docs/handoffs/INTERVIEW_STORY_BANK.md",
    "docs/handoffs/FINAL_HARDENING_CROSS_SURFACE_AUDIT_20260820.md",
    "docs/handoffs/FINAL_PORTFOLIO_SYNC_REPORT_20260820.md",
    "docs/handoffs/THIRD_PARTY_PROVENANCE.md",
    "docs/handoffs/EVALOPS_RESUME_BULLET_POOL.md",
    "docs/handoffs/TEACHING_CODEX_UPDATE.md",
    "docs/handoffs/resume_package/BULLET_CANDIDATES.md",
    "docs/handoffs/resume_package/EVIDENCE_MAP.md",
    "docs/handoffs/resume_package/FORBIDDEN_CLAIMS.md",
    "docs/handoffs/resume_package/INTERVIEW_STORIES.md",
    "docs/handoffs/resume_package/JD_KEYWORD_MAP.md",
    "docs/handoffs/resume_package/PROJECT_SUMMARY.md",
    "docs/handoffs/resume_package/ROLE_POSITIONING.md",
    "docs/handoffs/resume_package/SAFE_METRICS.md",
    "docs/resume/AGENT_EVAL_RESUME_EVIDENCE.md",
    "docs/learning/AGENT_EVALOPS_TUTORIAL.md",
    "docs/learning/EVALOPS_INTERVIEW_UPDATE.md",
)


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_current_status_surfaces_share_the_final_hardening_identity() -> None:
    status = _read("PROJECT_STATUS.md")
    report = _read("docs/final_hardening/FINAL_HARDENING_REPORT.md")

    for document in (status, report):
        assert "codex/final-evidence-hardening-v1" in document
        assert "22fda896a1b24b0cf41cd1402ead521f74758ac6" in document
        assert "20260820_0025" in document

    assert "portfolio-ready != release-ready != production-ready" in status
    assert "NOT_READY_TARGETED_NEGATIVE_SCALING" in status
    assert "Production readiness" in status


def test_resume_entrypoints_separate_current_agent_evidence_from_history() -> None:
    handoff = _read("docs/handoffs/RESUME_CODEX_HANDOFF.md")
    ledger = _read("docs/handoffs/RESUME_METRIC_LEDGER.md")
    bullets = _read("docs/handoffs/resume_package/BULLET_CANDIDATES.md")

    for document in (handoff, ledger):
        assert "default `main`" in document
        assert "1c2f9d93b488cacf7d5f7c953c8cce906e0f9be6" in document
        assert "33494481676" in document

    assert "codex/final-evidence-hardening-v1" in bullets

    for document in (handoff, ledger, bullets):
        assert "CURRENT_POSITIVE_RESUME" in document
        assert "HISTORICAL_NEGATIVE" in document
        assert "FORBIDDEN" in document

    for capability in (
        "canonical JSON/SHA-256",
        "common-case",
        "MCP stdio",
        "reconciliation",
    ):
        assert capability in handoff

    assert "826 non-integration tests" in ledger
    assert "783 passed, 33 skipped" in ledger
    assert "historical 2026-08-11 local rerun" in ledger


def test_teaching_handoff_covers_current_agent_eval_curriculum() -> None:
    teaching = _read("docs/handoffs/TEACHING_CODEX_HANDOFF.md")

    for required_reading in (
        "PROJECT_STATUS.md",
        "PROJECT_EVIDENCE_MAP.md",
        "FINAL_HARDENING_REPORT.md",
        "AGENT_EVALOPS_TUTORIAL.md",
        "AGENT_EVAL_RESUME_EVIDENCE.md",
        "RESUME_METRIC_LEDGER.md",
        "INTERVIEW_STORY_BANK.md",
    ):
        assert required_reading in teaching

    for topic in (
        "canonical JSON and SHA-256",
        "immutable Agent artifact ingestion",
        "seven deterministic trajectory metric extractors",
        "reported versus derived provenance",
        "common-case-only regression",
        "case-set, coverage and sufficiency fail-closed",
        "source-bound double review and adjudication",
        "MCP per-call authentication",
        "Agent evidence RLS and composite foreign keys",
        "orphan-object reconciliation",
        "PostgreSQL and object storage are not one atomic transaction",
    ):
        assert topic in teaching

    for workshop_field in (
        "Concept",
        "Real code chain",
        "SQL / transaction boundary",
        "Test",
        "Failure mode",
        "Trade-off",
        "Observed result",
        "Interview follow-up",
        "Independent answer",
        "Small modification exercise",
    ):
        assert workshop_field in teaching


def test_third_party_provenance_records_confirmed_and_unknown_origins() -> None:
    provenance = _read("docs/handoffs/THIRD_PARTY_PROVENANCE.md")

    for field in (
        "Project component / path",
        "External source",
        "URL",
        "Usage type",
        "External license",
        "Attribution / NOTICE requirement",
        "Current compliance",
        "Evidence",
        "Action",
        "Open risk",
    ):
        assert field in provenance

    for classification in ("CONCEPT_ONLY", "API_USAGE", "UNKNOWN"):
        assert classification in provenance

    assert "modelcontextprotocol/python-sdk" in provenance
    assert "langchain-ai/langgraph" in provenance
    assert "fixed fixture replay" in provenance
    assert "No copied or adapted third-party source was established" in provenance
    assert "architecture, constraints, gates and acceptance" in provenance


def test_current_resume_section_excludes_unsupported_positive_claims() -> None:
    handoff = _read("docs/handoffs/RESUME_CODEX_HANDOFF.md")
    current_section = (
        handoff.split("## Current Agent Evaluation Infrastructure bullets", maxsplit=1)[1]
        .split("## Historical scheduler evidence", maxsplit=1)[0]
        .lower()
    )

    for unsupported in (
        "production-ready",
        "exactly-once",
        "seven verified evaluators",
        "linear scaling",
        "atomic postgresql/s3",
    ):
        assert unsupported not in current_section

    assert "seven deterministic trajectory metric extractors" in current_section


def test_old_scheduler_branch_is_only_historical_in_current_status() -> None:
    status = _read("PROJECT_STATUS.md")
    current, historical = status.split("## Historical scheduler/archive baseline", maxsplit=1)

    assert "codex/evidence-gate-1" not in current
    assert "codex/evidence-gate-1" in historical


def test_current_documentation_local_links_exist() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    missing: list[str] = []

    for relative_path in CURRENT_DOCUMENTS:
        document_path = PROJECT_ROOT / relative_path
        for raw_target in link_pattern.findall(document_path.read_text(encoding="utf-8")):
            target = raw_target.strip("<>").split("#", maxsplit=1)[0]
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            resolved = (document_path.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{relative_path} -> {raw_target}")

    assert not missing, "Missing local documentation links:\n" + "\n".join(missing)
