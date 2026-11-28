from __future__ import annotations

from fastapi import FastAPI
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIASGIMiddleware
from slowapi.util import get_remote_address
from slowapi.extension import _rate_limit_exceeded_handler


from backend.app.core.config import settings

# Counts live in Redis so every API process and restart shares them; in process memory,
# each of N API workers would allow its own full quota. If Redis is unreachable, limits are
# counted in memory until it's back, rather than failing every rate-limited request.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    key_prefix="ragnex",
    in_memory_fallback_enabled=True,
)


def setup_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    # The ASGI variant: the BaseHTTPMiddleware one adds overhead to every request.
    app.add_middleware(SlowAPIASGIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
