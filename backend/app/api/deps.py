"""Reusable API dependencies."""

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import is_expired, token_digest
from app.db.session import get_db
from app.models.models import AuthSession, User


def get_current_session(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=settings.session_cookie_name),
) -> AuthSession:
    token = authorization.removeprefix("Bearer ").strip() if authorization and authorization.startswith("Bearer ") else session_cookie
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token), AuthSession.revoked_at.is_(None)))
    if not session or is_expired(session.expires_at):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    return session


def get_current_user(session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)) -> User:
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator permission required")
    return user


def require_csrf(
    request: Request,
    session: AuthSession = Depends(get_current_session),
    csrf_cookie: str | None = Cookie(default=None, alias=settings.csrf_cookie_name),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthSession:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return session
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return session


__all__ = ["get_db", "get_current_session", "get_current_user", "require_admin", "require_csrf"]
