from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from api.app.ai.graph import classify_route
from evals.evaluators.quality import evaluate_records, gate, regressions

ROOT = Path(__file__).resolve().parents[4]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def deterministic_replay(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for case in dataset:
        route, _ = classify_route(case["question"])
        records.append(
            {
                **case,
                "route": route,
                "refused": route == "unsupported",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate agent predictions against release gates")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/datasets/routes-v1.jsonl")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--baseline", type=Path, default=ROOT / "evals/baselines/release-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evals/results/latest.json")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    records = (
        read_jsonl(args.predictions)
        if args.predictions
        else deterministic_replay(read_jsonl(args.dataset))
    )
    metrics = evaluate_records(records)
    passed, failures = gate(metrics)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))["metrics"]
    regression_failures = regressions(metrics, baseline)
    report = {
        "metrics": metrics,
        "release_passed": passed and not regression_failures,
        "gate_failures": failures,
        "regressions": regression_failures,
        "record_count": len(records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    incomplete_only = failures and all(failure.endswith("missing") for failure in failures)
    if not report["release_passed"] and not (args.allow_incomplete and incomplete_only):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
