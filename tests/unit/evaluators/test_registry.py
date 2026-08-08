import pytest

from app.evaluators.base import (
    EvaluatorCategory,
    UnsupportedEvaluatorError,
    build_evaluator,
    registered_evaluators,
)
from app.evaluators.retrieval_citation import RetrievalCitationEvaluator


def test_registry_describes_deterministic_and_operational_plugins() -> None:
    descriptors = {item.kind: item for item in registered_evaluators()}

    assert set(descriptors) == {"basic_answer", "execution", "retrieval_citation"}
    assert descriptors["basic_answer"].category is EvaluatorCategory.DETERMINISTIC
    assert descriptors["retrieval_citation"].category is EvaluatorCategory.DETERMINISTIC
    assert descriptors["execution"].category is EvaluatorCategory.OPERATIONAL
    assert all(item.implementation_version == "builtin-v1" for item in descriptors.values())
    assert all(item.llm_judge is False for item in descriptors.values())


def test_registry_builds_retrieval_plugin_and_rejects_unknown_type() -> None:
    assert isinstance(build_evaluator("retrieval_citation", {}), RetrievalCitationEvaluator)

    with pytest.raises(UnsupportedEvaluatorError):
        build_evaluator("llm_judge", {})


def test_every_registered_evaluator_has_a_working_factory() -> None:
    for descriptor in registered_evaluators():
        assert build_evaluator(descriptor.kind, {}) is not None
