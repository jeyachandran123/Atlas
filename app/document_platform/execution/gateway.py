"""One natural-language document task, from stored file to downloadable result.

The runner does the thinking; this owns the transaction, the artifact row and
the bytes. It deliberately reuses the Generation layer's artifact table and
storage rather than inventing a second kind of output: a file produced by
generated code is the same thing to a user as a file produced by the builders -
it is listed in the same place, downloaded through the same signed URL, and
expires under the same rules.

Not every task produces a file. A question ("how many dishes are Halal and
Pureed?") is answered by the same pipeline, computed over every row rather than
over the handful retrieval would have shown the model. That case stores no
artifact and returns the answer.
"""

from __future__ import annotations

import hashlib
import json
from typing import AsyncIterator

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.document_platform.execution.runner import DocumentTaskRunner, TaskResult
from app.document_platform.generation.lifecycle import (
    ALLOWED_TRANSITIONS,
    GenerationLifecycle,
)
from app.document_platform.generation.repository import GenerationRepository
from app.document_platform.generation.metrics import GenerationMetrics
from app.storage import get_blob_storage

STORAGE_PREFIX = "generated_artifacts"

CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "json": "application/json",
    "md": "text/markdown",
    "txt": "text/plain",
}


def _slug(text: str, fallback: str = "result") -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else " " for c in text)
    words = keep.split()
    return "-".join(words[:8]).lower()[:80] or fallback


class DocumentTaskGateway:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = GenerationRepository(db)
        self._storage = get_blob_storage(STORAGE_PREFIX)
        self._runner = DocumentTaskRunner()

    async def run_stream(
        self, *, user_id: str, org_id: str, document_id: str, filename: str,
        data: bytes, request: str, requested_format: str | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        """Yields ("stage"|"done"|"error", payload) as the task progresses.

        The stages are forwarded rather than summarised because the work takes
        tens of seconds and the steps mean something to a person: "fixing_code,
        attempt 2 of 3" is the difference between a system that looks stuck and
        one that is visibly recovering from a normal mistake.
        """
        artifact = await self._repo.create_artifact(
            user_id=user_id, org_id=org_id, prompt=request,
            format_name=(requested_format or "auto"),
            source_document_id=document_id,
        )
        await self._db.flush()
        yield "meta", {"artifact_id": artifact.id, "correlation_id": artifact.correlation_id}

        result: TaskResult | None = None
        try:
            await self._repo.transition(artifact, GenerationLifecycle.PLANNING)
            async for kind, payload in self._runner.run_streaming(
                data, filename, request, requested_format=requested_format,
            ):
                if kind == "result":
                    result = payload["result"]
                else:
                    yield "stage", {"stage": kind, "detail": payload}

            assert result is not None
            if not result.ok:
                await self._fail(artifact, result.error)
                yield "error", {
                    "message": result.error,
                    "attempts": result.attempt_count,
                    "code": result.code,
                }
                return

            if result.kind == "answer":
                # Nothing to store; the computation is the deliverable.
                await self._fail(artifact, "", cancelled=True)
                await self._db.commit()
                yield "done", {
                    "kind": "answer",
                    "answer": result.answer,
                    "attempts": result.attempt_count,
                    "llm_ms": result.llm_ms,
                    "sandbox_ms": result.sandbox_ms,
                    "code": result.code,
                }
                return

            ext = result.output_name.rsplit(".", 1)[-1].lower()
            content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
            storage_key = f"{org_id}/{artifact.id}.{ext}"
            # The artifact lifecycle is a chain, and every artifact walks all of
            # it. Writing code is this layer's planning; running it is the
            # transform; the file it produced is the build. Naming the steps
            # this way keeps generated-code artifacts indistinguishable from
            # built ones wherever they are listed or audited.
            await self._repo.transition(artifact, GenerationLifecycle.TRANSFORMING)
            await self._repo.transition(artifact, GenerationLifecycle.BUILDING)
            await self._repo.transition(artifact, GenerationLifecycle.STORING)
            await self._storage.put(storage_key, result.output_bytes, content_type)

            await self._repo.transition(artifact, GenerationLifecycle.READY)
            title = _slug(request.strip().splitlines()[0] if request.strip() else "result")
            await self._repo.finish_artifact(
                artifact,
                metrics=GenerationMetrics(
                    planning_ms=result.llm_ms,
                    build_ms=result.sandbox_ms,
                    total_ms=result.llm_ms + result.sandbox_ms,
                    size_bytes=len(result.output_bytes),
                ),
                title=title.replace("-", " ").title(),
                filename=f"{title}.{ext}",
                storage_key=storage_key,
                content_type=content_type,
                checksum=hashlib.sha256(result.output_bytes).hexdigest(),
                size_bytes=len(result.output_bytes),
                builder_name="generated_code",
                grounded=True,
                llm_provider="codegen",
                llm_model="",
            )
            await self._db.commit()
            yield "done", {
                "kind": "file",
                "artifact_id": artifact.id,
                "filename": f"{title}.{ext}",
                "size_bytes": len(result.output_bytes),
                "attempts": result.attempt_count,
                "llm_ms": result.llm_ms,
                "sandbox_ms": result.sandbox_ms,
                "summary": result.answer,
                "preview": result.preview.as_dict() if result.preview else None,
                "code": result.code,
            }
        except Exception as e:  # noqa: BLE001 - the turn must end with a verdict
            logger.exception(f"Document task {artifact.id} crashed: {e}")
            await self._fail(artifact, f"{type(e).__name__}: {e}")
            yield "error", {"message": "The task could not be completed.",
                            "artifact_id": artifact.id}

    async def _fail(self, artifact, error: str, cancelled: bool = False) -> None:
        """Close the artifact row honestly, whatever happened.

        A row left in-flight is worse than one marked failed: it shows up as a
        document that is still being generated, forever.
        """
        try:
            state = GenerationLifecycle.CANCELLED if cancelled else GenerationLifecycle.FAILED
            current = GenerationLifecycle(artifact.status)
            if state not in ALLOWED_TRANSITIONS.get(current, set()):
                # Already terminal (or somewhere FAILED cannot be reached from);
                # the row is closed, and forcing a transition would only raise.
                artifact.status = state.value
            else:
                await self._repo.transition(artifact, state)
            await self._repo.finish_artifact(
                artifact, metrics=GenerationMetrics(), error=error or None,
            )
            await self._db.commit()
        except Exception as e:  # noqa: BLE001 - last resort; the log is the record
            logger.error(f"Could not close artifact {artifact.id}: {e}")

    @staticmethod
    def sse(kind: str, payload: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
