from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def promote(input_path: Path, output_path: Path, reviewed_by: str) -> dict[str, Any]:
    trace = json.loads(input_path.read_text(encoding="utf-8"))
    question = str(trace["question"]).strip()
    expected = trace.get("expected")
    if not question or not isinstance(expected, dict):
        raise ValueError("reviewed trace requires question and expected object")
    case = {
        "id": "feedback-" + hashlib.sha256(question.encode()).hexdigest()[:12],
        "question": question,
        "expected": expected,
        "source_run_id": trace.get("run_id"),
        "reviewed_by": reviewed_by,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(case, sort_keys=True) + "\n")
    return case


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote a human-reviewed negative trace")
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evals/datasets/reviewed-feedback-v1.jsonl",
    )
    parser.add_argument("--reviewed-by", required=True)
    args = parser.parse_args()
    print(json.dumps(promote(args.input, args.output, args.reviewed_by), indent=2))


if __name__ == "__main__":
    main()
