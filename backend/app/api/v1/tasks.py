from __future__ import annotations

from typing import Any, Optional

from celery.result import AsyncResult
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.core.celery_app import celery_app
from backend.app.core.deps import get_current_user
from backend.app.models.user import User

router = APIRouter()


class TaskStatusResponse(BaseModel):
    id: str
    state: str
    ready: bool
    successful: bool
    result: Optional[Any] = None
    traceback: Optional[str] = None


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
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)) -> TaskStatusResponse:
    # user currently unused; kept to ensure auth required
    _ = current_user

    res: AsyncResult = celery_app.AsyncResult(task_id)

    payload = TaskStatusResponse(
        id=task_id,
        state=res.state,
        ready=res.ready(),
        successful=res.successful(),
    )

    if res.ready():
        try:
            payload.result = _json_safe(res.result)
        except Exception:
            payload.result = None

    # Traceback only makes sense on failures
    if res.failed():
        try:
            payload.traceback = res.traceback
        except Exception:
            payload.traceback = None

    return payload
