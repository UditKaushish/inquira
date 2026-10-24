"""Onboarding, authentication and user management."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AfterValidator, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from inquira.api.deps import (
    admin_user,
    clear_session_cookie,
    client_ip,
    current_user,
    optional_user,
    set_session_cookie,
    user_json,
)
from inquira.core import ratelimit
from inquira.core.config import get_settings
from inquira.core.errors import ApiError, not_found
from inquira.core.security import hash_password, verify_password
from inquira.db import User, get_db
from inquira.engine.demo import demo_available
from inquira.services import settings_store

router = APIRouter()

Password = Field(min_length=10, max_length=256)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$|^[^@\s]+@localhost$")


def _check_email(v: str) -> str:
    # Syntax check only: self-hosted teams often use internal domains (.local, .internal, .test)
    # that strict deliverability validators reject.
    v = v.strip().lower()
    if len(v) > 320 or not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address")
    return v


EmailStr = Annotated[str, AfterValidator(_check_email)]


class AdminIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Password


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserCreateIn(AdminIn):
    role: Literal["admin", "member"] = "member"


class UserPatchIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    role: Literal["admin", "member"] | None = None


def _admin_exists(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) > 0


@router.get("/setup/status")
def setup_status(db: Session = Depends(get_db)) -> dict:
    has_admin = _admin_exists(db)
    has_ds = settings_store.load_datasource(db) is not None
    has_llm = settings_store.load_llm_config(db) is not None
    return {"needs_admin": not has_admin, "has_datasource": has_ds, "has_llm": has_llm,
            "completed": has_admin and has_ds and has_llm, "demo_available": demo_available()}


@router.post("/setup/admin")
def create_first_admin(body: AdminIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ratelimit.enforce("setup", client_ip(request), get_settings().login_rate_limit)
    if _admin_exists(db):
        raise ApiError(409, "already_setup", "An administrator already exists. Please sign in.")
    user = User(email=body.email.lower(), name=body.name.strip(), password_hash=hash_password(body.password),
                role="admin")
    db.add(user)
    db.commit()
    set_session_cookie(response, user)
    return {"user": user_json(user)}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    rate = get_settings().login_rate_limit
    ratelimit.enforce("login-ip", client_ip(request), rate)
    ratelimit.enforce("login-email", body.email.lower(), rate)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(body.password, user.password_hash if user else None):
        raise ApiError(401, "invalid_credentials", "Email or password is incorrect.")
    set_session_cookie(response, user)
    return {"user": user_json(user)}


@router.post("/auth/logout")
def logout(response: Response, user: User | None = Depends(optional_user), db: Session = Depends(get_db)) -> dict:
    if user is not None:
        user.token_version += 1  # revoke every outstanding session for this user
        db.commit()
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user_json(user)}


@router.get("/users")
def list_users(_: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    return {"users": [user_json(u) for u in db.scalars(select(User).order_by(User.created_at))]}


@router.post("/users")
def create_user(body: UserCreateIn, _: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise ApiError(409, "email_taken", "A user with that email already exists.")
    user = User(email=body.email.lower(), name=body.name.strip(), password_hash=hash_password(body.password),
                role=body.role)
    db.add(user)
    db.commit()
    return {"user": user_json(user)}


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserPatchIn, admin: User = Depends(admin_user),
                db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("User")
    if body.role and body.role != user.role:
        if user.id == admin.id and body.role != "admin":
            raise ApiError(400, "last_admin", "You can't remove your own admin role.")
        user.role = body.role
        user.token_version += 1
    if body.name:
        user.name = body.name.strip()
    db.commit()
    return {"user": user_json(user)}


@router.delete("/users/{user_id}")
def delete_user(user_id: str, admin: User = Depends(admin_user), db: Session = Depends(get_db)) -> dict:
    if user_id == admin.id:
        raise ApiError(400, "self_delete", "You can't delete your own account.")
    user = db.get(User, user_id)
    if user is None:
        raise not_found("User")
    db.delete(user)
    db.commit()
    return {"ok": True}
