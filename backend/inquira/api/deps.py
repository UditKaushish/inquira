from __future__ import annotations

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session

from inquira.core.config import get_settings
from inquira.core.errors import ApiError
from inquira.core.security import create_session_token, decode_session_token
from inquira.db import User, get_db

COOKIE_NAME = "inquira_session"


def set_session_cookie(response: Response, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user.id, user.token_version),
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/api",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/api")


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    claims = decode_session_token(token)
    if not claims:
        return None
    user = db.get(User, claims["sub"])
    if user is None or user.token_version != claims.get("ver"):
        return None
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise ApiError(401, "unauthenticated", "Please sign in.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "forbidden", "Admin access required.")
    return user


def client_ip(request: Request) -> str:
    """Client address for rate limiting.

    Forwarding headers are only honoured when INQUIRA_TRUST_PROXY_HEADERS is set, i.e. the API is
    reachable *only* through a proxy that overwrites them (our nginx config, Vercel). Otherwise any
    client could send a fake X-Forwarded-For and get a fresh rate-limit bucket per request.
    """
    if get_settings().trust_proxy_headers:
        real = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
        if real.strip():
            return real.strip()
    return request.client.host if request.client else "unknown"


def user_json(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "created_at": u.created_at.isoformat() + "Z"}
