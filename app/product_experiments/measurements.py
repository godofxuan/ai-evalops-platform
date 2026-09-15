"""Product v2 measurements; absent and inapplicable scores are never fabricated."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.product_experiments.observation_contract import MAX_PRODUCT_ANSWER_CHARS


class ProductCaseMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=20_000)
    task_success: float = Field(ge=0, le=1)
    citation_correctness: float | None = Field(default=None, ge=0, le=1)
    citation_recall: float | None = Field(default=None, ge=0, le=1)
    citation_precision: float | None = Field(default=None, ge=0, le=1)
    tool_error_rate: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    answer: str = Field(max_length=MAX_PRODUCT_ANSWER_CHARS)
    citations: list[dict[str, JsonValue]] = Field(default_factory=list)
    trace_id: str | None = None


class ProductArmResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["evalops.product-arm/2.0"] = "evalops.product-arm/2.0"
    arm: Literal["baseline", "candidate"]
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[ProductCaseMeasurement] = Field(min_length=2)

    @model_validator(mode="after")
    def unique_cases(self) -> "ProductArmResult":
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case identity")
        return self
