from app.domain.evaluation import EvaluationCase, EvaluationResult, TargetResult


class ExecutionEvaluator:
    def evaluate(
        self,
        case: EvaluationCase,
        target_result: TargetResult,
        *,
        attempt_number: int,
    ) -> EvaluationResult:
        del case
        usage = target_result.token_usage
        return EvaluationResult(
            metrics={
                "execution_success": True,
                "latency_ms": target_result.latency_ms,
                "input_tokens": None if usage is None else usage.input_tokens,
                "output_tokens": None if usage is None else usage.output_tokens,
                "attempt_count": attempt_number,
                "succeeded_after_retry": attempt_number > 1,
            }
        )
