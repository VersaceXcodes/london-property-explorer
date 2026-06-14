from evals.evaluators.quality import evaluate_records, gate


def test_release_gate_accepts_metrics_at_threshold() -> None:
    records = [
        {
            "expected_route": "unsupported",
            "route": "unsupported",
            "refused": True,
            "critical_injection": True,
            "sql_args_valid": True,
            "numeric_grounded": True,
            "citations_valid": True,
            "retrieval_hit_at_5": True,
            "task_success": True,
            "first_event_ms": 100,
            "latency_ms": 500,
            "cost_usd": 0.001,
        }
    ]
    passed, failures = gate(evaluate_records(records))
    assert passed
    assert failures == []
