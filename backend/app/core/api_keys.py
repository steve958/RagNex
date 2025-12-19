from __future__ import annotations

import hashlib
import secrets


def generate_api_key(prefix: str = "rk") -> str:
    # Example: rk_<random>
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    # Store only a hash in DB
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()
