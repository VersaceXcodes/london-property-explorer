from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from api.app.ai.redaction import redact_payload


class TraceManager:
    def __init__(self, *, api_key: str | None, project: str, enabled: bool) -> None:
        self.enabled = enabled and bool(api_key)
        self.project = project
        self._client: Any = None
        self._local_runs: dict[str, dict[str, Any]] = {}
        if self.enabled:
            from langsmith import Client

            self._client = Client(api_key=api_key)

    def start(self, run_id: UUID, inputs: dict[str, Any], metadata: dict[str, Any]) -> None:
        safe_inputs = redact_payload(inputs)
        self._local_runs[str(run_id)] = {"inputs": safe_inputs, "metadata": metadata, "spans": []}
        if self._client is None:
            return
        try:
            self._client.create_run(
                name="lpe-agent",
                run_id=run_id,
                run_type="chain",
                inputs=safe_inputs,
                project_name=self.project,
                start_time=datetime.now(UTC),
                extra={"metadata": metadata},
            )
        except Exception:
            self.enabled = False

    @asynccontextmanager
    async def span(
        self,
        root_run_id: UUID,
        name: str,
        inputs: dict[str, Any] | None = None,
    ) -> AsyncIterator[None]:
        started = time.perf_counter()
        child_id = uuid4()
        safe_inputs = redact_payload(inputs or {})
        if self._client is not None and self.enabled:
            try:
                self._client.create_run(
                    name=name,
                    run_id=child_id,
                    parent_run_id=root_run_id,
                    run_type="chain",
                    inputs=safe_inputs,
                    project_name=self.project,
                    start_time=datetime.now(UTC),
                )
            except Exception:
                self.enabled = False
        error: str | None = None
        try:
            yield
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000)
            run = self._local_runs.get(str(root_run_id))
            if run is not None:
                run["spans"].append({"name": name, "duration_ms": duration_ms, "error": error})
            if self._client is not None and self.enabled:
                try:
                    self._client.update_run(
                        child_id,
                        end_time=datetime.now(UTC),
                        outputs={"duration_ms": duration_ms},
                        error=error,
                    )
                except Exception:
                    self.enabled = False

    def finish(self, run_id: UUID, outputs: dict[str, Any], error: str | None = None) -> None:
        safe_outputs = redact_payload(outputs)
        run = self._local_runs.get(str(run_id))
        if run is not None:
            run["outputs"] = safe_outputs
            run["error"] = error
        if self._client is not None and self.enabled:
            try:
                self._client.update_run(
                    run_id,
                    end_time=datetime.now(UTC),
                    outputs=safe_outputs,
                    error=error,
                )
            except Exception:
                self.enabled = False

    def feedback(
        self,
        run_id: UUID,
        *,
        score: int,
        reason: str | None,
        correction: str | None,
    ) -> bool:
        if str(run_id) not in self._local_runs:
            return False
        if self._client is None or not self.enabled:
            return False
        comment = "\n".join(part for part in [reason, correction] if part)
        try:
            self._client.create_feedback(
                run_id=run_id,
                key="user_score",
                score=score,
                comment=str(redact_payload(comment)),
            )
        except Exception:
            self.enabled = False
            return False
        return True
