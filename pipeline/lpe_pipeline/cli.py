from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .build import PipelineError, build_dataset


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Build the London Property Explorer load dataset.")
    root.add_argument("--ppd", type=Path, required=True, help="Path to pp-complete.csv")
    root.add_argument("--onspd", type=Path, required=True, help="Path to the ONSPD CSV")
    root.add_argument(
        "--district-source",
        type=Path,
        action="append",
        required=True,
        help="GeoJSON boundary source; repeat for multiple files",
    )
    root.add_argument("--output-dir", type=Path, default=Path("pipeline/output"))
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    for path in (args.ppd, args.onspd, *args.district_source):
        if not path.is_file():
            parser().error(f"source does not exist: {path}")
    try:
        manifest = build_dataset(args.ppd, args.onspd, args.district_source, args.output_dir)
    except PipelineError as exc:
        parser().exit(2, f"pipeline failed: {exc}\n")
    print(json.dumps({"output": str(args.output_dir), "counts": manifest["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
