from __future__ import annotations

import time

from backend.app.core.celery_app import celery_app


@celery_app.task(bind=True, name="backend.app.tasks.embedding.embed_texts")
def embed_texts(self, texts: list[str]) -> dict:
    """Placeholder embedding task.

    Phase 3 (P3-2) will implement real embedding providers.
    """

    time.sleep(0.01)
    return {"count": len(texts), "dims": 0}
