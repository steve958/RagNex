from __future__ import annotations

from typing import Any, Optional

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.core.celery_app import celery_app
from backend.app.core.deps import require_tenant_membership

router = APIRouter()


class TaskStatusResponse(BaseModel):
    id: str
    state: str
    ready: bool
    successful: bool
    result: Optional[Any] = None


def _json_safe(value: Any) -> Any:
    # Celery results can contain non-JSON-serializable objects.
    # For now we keep it simple; real tasks should return JSON-serializable payloads.
    try:
        from pydantic_core import to_jsonable_python

        return to_jsonable_python(value)
    except Exception:
        try:
            import json

            json.dumps(value)
            return value
        except Exception:
            return str(value)


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, ctx=Depends(require_tenant_membership)) -> TaskStatusResponse:
    """Status of a background task. A finished task's result is only shown to its own tenant
    (our tasks return a dict carrying tenant_id); tracebacks are never returned."""
    tenant_id, _user = ctx
    res: AsyncResult = celery_app.AsyncResult(task_id)

    if not res.ready():
        # Celery reports PENDING for unknown ids too, so this reveals nothing.
        return TaskStatusResponse(id=task_id, state=res.state, ready=False, successful=False)

    result = res.result if res.successful() else None
    if not isinstance(result, dict) or result.get("tenant_id") != str(tenant_id):
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        id=task_id, state=res.state, ready=True, successful=True, result=_json_safe(result)
    )
