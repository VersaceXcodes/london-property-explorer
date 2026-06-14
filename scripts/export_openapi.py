from __future__ import annotations

from pathlib import Path

import yaml

from api.app.main import app

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = ROOT / "docs/openapi.yaml"
    target.write_text(
        yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    main()
