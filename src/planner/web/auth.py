"""Optional single shared password (no user accounts)."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from urllib.parse import quote

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "planner_session"
MAX_AGE = 60 * 60 * 24 * 30
OPEN_PREFIXES = ("/healthz", "/login", "/static")


def serializer(password: str) -> URLSafeTimedSerializer:
    secret = hashlib.sha256(("planner-session:" + password).encode()).hexdigest()
    return URLSafeTimedSerializer(secret, salt="planner")


def password_ok(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


def make_token(password: str) -> str:
    return serializer(password).dumps("ok")


def token_ok(token: str | None, password: str) -> bool:
    if not token:
        return False
    try:
        return bool(serializer(password).loads(token, max_age=MAX_AGE) == "ok")
    except BadSignature:
        return False


def install(app: object, password: str) -> None:
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)

    @app.middleware("http")
    async def _guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path.startswith(OPEN_PREFIXES) or token_ok(request.cookies.get(COOKIE), password):
            return await call_next(request)
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        nxt = quote(path + (("?" + request.url.query) if request.url.query else ""))
        return RedirectResponse(f"/login?next={nxt}", status_code=303)
