"""Shared settings for outgoing HTTP clients."""

from __future__ import annotations

import ssl
from functools import cache

import httpx


@cache
def tls_context() -> ssl.SSLContext:
    """The TLS settings httpx uses by default (certifi's CA bundle, or SSL_CERT_FILE /
    SSL_CERT_DIR when set), built once per process.

    httpx builds and loads the CA bundle anew for every client. Search creates a client per
    query it embeds, and that loading was about 7% of the API's CPU under load
    (docs/performance.md). Pass it as `verify=` to clients made per request.
    """
    return httpx.create_ssl_context()
