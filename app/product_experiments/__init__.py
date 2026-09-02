"""Usable paired-evaluation product workflow built on EvalOps evidence contracts."""

from app.product_experiments.external_evidence import (
    ExternalAggregateEvidenceReference,
    ExternalEvidenceError,
    verify_external_aggregate_evidence_files,
)
from app.product_experiments.runner import ProductExperimentResult, run_experiment
from app.product_experiments.spec import ExperimentSpec, load_experiment_spec

__all__ = [
    "ExperimentSpec",
    "ExternalAggregateEvidenceReference",
    "ExternalEvidenceError",
    "ProductExperimentResult",
    "load_experiment_spec",
    "run_experiment",
    "verify_external_aggregate_evidence_files",
]
