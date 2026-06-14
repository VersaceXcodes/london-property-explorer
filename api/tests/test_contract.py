from __future__ import annotations

from pathlib import Path

import yaml

from api.app.main import app


def test_committed_openapi_matches_generated_contract() -> None:
    committed = yaml.safe_load(Path("docs/openapi.yaml").read_text(encoding="utf-8"))
    assert committed == app.openapi()
