"""Safe operation (FR20): strict Origin check, rate limits, security headers.

No sign-in and no cookies.  Browsers always send an Origin header on cross-site and on
POST requests, so every state-changing or costly request (POST) must carry an Origin that is
on the allow-list.  Read-only GETs are open (the documented data API) but rate-limited.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from megavir.config import settings


def client_ip(request: Request) -> str:
    # Behind nginx the real address is in X-Real-IP (set by our nginx config, not by visitors).
    if settings_trust_proxy():
        ip = request.headers.get("x-real-ip")
        if ip:
            return ip.strip()
    return request.client.host if request.client else "unknown"


def settings_trust_proxy() -> bool:
    import os

    return os.environ.get("MEGAVIR_TRUST_PROXY", "0") == "1"


class SlidingWindow:
    """In-memory per-key limiter (one server, two processes: limits are per process)."""

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window = window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                return False, retry
            q.append(now)
            if len(self.hits) > 50_000:  # forget idle visitors
                for k in [k for k, v in self.hits.items() if not v][:10_000]:
                    del self.hits[k]
            return True, 0


class OriginAndHeaders(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.limiter = SlidingWindow(settings().analysis_per_minute_per_ip, 60.0)
        # map tiles come in bursts (dozens per pan); this only stops bulk downloading through us
        self.map_limiter = SlidingWindow(settings().basemap_per_minute_per_ip, 60.0)

    async def dispatch(self, request: Request, call_next):
        allowed = set(settings().allowed_origins)
        origin = request.headers.get("origin")
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not origin or origin not in allowed:
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        limiter = (
            self.limiter
            if request.url.path.startswith(("/analysis", "/ai", "/reports", "/v1", "/context", "/cases"))
            else self.map_limiter
            if request.url.path.startswith("/basemap")
            else None
        )
        if limiter:
            ok, retry = limiter.allow(client_ip(request))
            if not ok:
                return JSONResponse(
                    {"detail": "Too many requests, please wait a moment."},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = (
            "DENY" if not request.url.path.startswith("/embed") else "ALLOWALL"
        )
        response.headers["Cross-Origin-Resource-Policy"] = (
            "same-site" if not request.url.path.startswith(("/v1", "/embed")) else "cross-origin"
        )
        if origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        elif request.url.path.startswith("/v1"):
            response.headers["Access-Control-Allow-Origin"] = "*"  # open read-only data API
        return response
