from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.domain.enums import ReviewTaskStatus

ReviewScore = int | None


class ReviewLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_relevance: ReviewScore = Field(default=None, ge=1, le=5)
    answer_correctness: ReviewScore = Field(default=None, ge=1, le=5)
    answer_completeness: ReviewScore = Field(default=None, ge=1, le=5)
    citation_support: ReviewScore = Field(default=None, ge=1, le=5)
    refusal_appropriateness: ReviewScore = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def require_one_label(self) -> "ReviewLabels":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one review dimension is required")
        return self


class ReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    question: str
    reference_answer: JsonValue | None
    candidate_answer: JsonValue | None
    citations: list[JsonValue]
    sources: list[JsonValue]
    terminal_state: str | None = None
    trajectory: list[dict[str, JsonValue]] = Field(default_factory=list)
    evaluator_results: dict[str, JsonValue] = Field(default_factory=dict)


class ReviewSubmissionRead(BaseModel):
    id: UUID
    task_id: UUID
    labels: ReviewLabels
    comment: str | None
    created_at: datetime


class ReviewAdjudicationRead(BaseModel):
    id: UUID
    task_id: UUID
    labels: ReviewLabels
    rationale: str
    created_at: datetime


class ReviewTaskRead(BaseModel):
    id: UUID
    run_id: UUID
    case_id: str
    status: ReviewTaskStatus
    packet: ReviewPacket
    own_submission: ReviewSubmissionRead | None
    created_at: datetime


class CreateReviewTasks(BaseModel):
    sample_size: int = Field(default=20, ge=1, le=200)
    source: Literal["case_result", "agent_artifact"] = "case_result"


class SubmitReview(BaseModel):
    labels: ReviewLabels
    comment: str | None = Field(default=None, max_length=1_000)


class AdjudicateReview(BaseModel):
    labels: ReviewLabels
    rationale: str = Field(min_length=1, max_length=2_000)


class ReviewMetricsRead(BaseModel):
    run_id: UUID
    task_count: int
    paired_tasks: int
    agreed_tasks: int
    disputed_tasks: int
    adjudicated_tasks: int
    paired_labels: int
    exact_agreement: float | None
    cohen_kappa: float | None
