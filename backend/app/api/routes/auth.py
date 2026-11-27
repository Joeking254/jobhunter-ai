from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_csrf
from app.core.config import settings
from app.core.security import expires_in, hash_password, is_expired, new_token, token_digest, utcnow, validate_password, verify_password
from app.models.models import AuthSession, LoginAttempt, PasswordResetToken, User, UserSettings
from app.schemas.auth import LoginRequest, PasswordResetConfirm, PasswordResetRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    common = {"secure": settings.cookie_secure, "samesite": "lax", "domain": settings.cookie_domain, "path": "/"}
    response.set_cookie(settings.session_cookie_name, session_token, max_age=settings.session_ttl_minutes * 60, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie_name, csrf_token, max_age=settings.session_ttl_minutes * 60, httponly=False, **common)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.session_cookie_name, domain=settings.cookie_domain, path="/")
    response.delete_cookie(settings.csrf_cookie_name, domain=settings.cookie_domain, path="/")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _rate_limited(db: Session, email: str, ip_address: str | None) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.login_rate_limit_window_minutes)
    query = select(func.count(LoginAttempt.id)).where(LoginAttempt.created_at >= cutoff, LoginAttempt.succeeded.is_(False))
    query = query.where((LoginAttempt.email == email) | (LoginAttempt.ip_address == ip_address))
    return int(db.scalar(query) or 0) >= settings.login_rate_limit_attempts


def _create_session(db: Session, user: User, request: Request) -> tuple[str, str]:
    token = new_token()
    csrf_token = new_token()
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires_in(settings.session_ttl_minutes), ip_address=_client_ip(request), user_agent=request.headers.get("user-agent")))
    return token, csrf_token


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    try:
        validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    email = str(payload.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    has_admin = db.scalar(select(User.id).where(User.is_admin.is_(True))) is not None
    user = User(email=email, password_hash=hash_password(payload.password), first_name=payload.first_name.strip(), last_name=payload.last_name.strip(), is_admin=not has_admin, is_verified=False)
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    token, csrf = _create_session(db, user, request)
    db.add(LoginAttempt(email=email, ip_address=_client_ip(request), succeeded=True))
    db.commit()
    _set_auth_cookies(response, token, csrf)
    return user


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    email = str(payload.email).lower()
    ip_address = _client_ip(request)
    if _rate_limited(db, email, ip_address):
        raise HTTPException(status_code=429, detail="Too many login attempts; try again later")
    user = db.scalar(select(User).where(User.email == email))
    locked = bool(user and user.locked_until and not is_expired(user.locked_until))
    valid = user is not None and user.is_active and not locked and verify_password(payload.password, user.password_hash)
    db.add(LoginAttempt(email=email, ip_address=ip_address, succeeded=valid))
    if not valid:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.failed_login_lockout_threshold:
                user.locked_until = utcnow() + timedelta(minutes=settings.failed_login_lockout_minutes)
        db.commit()
        raise HTTPException(status_code=423 if locked else 401, detail="Account temporarily locked" if locked else "Invalid email or password")
    user.failed_login_count = 0
    user.last_login_at = utcnow()
    token, csrf = _create_session(db, user, request)
    db.commit()
    _set_auth_cookies(response, token, csrf)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, session: AuthSession = Depends(require_csrf), db: Session = Depends(get_db)) -> None:
    session.revoked_at = utcnow()
    db.commit()
    _clear_auth_cookies(response)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/account")
def get_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    user_settings = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    sessions = list(
        db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )
    )
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_admin": user.is_admin,
        "is_verified": user.is_verified,
        "last_login_at": user.last_login_at,
        "timezone": user_settings.timezone if user_settings else "UTC",
        "locale": user_settings.locale if user_settings else "en",
        "active_sessions": [
            {"id": s.id, "ip_address": s.ip_address, "user_agent": s.user_agent, "created_at": s.created_at, "expires_at": s.expires_at}
            for s in sessions
        ],
    }


@router.put("/account")
def update_account(
    payload: dict,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    for field in ("first_name", "last_name"):
        if field in payload and isinstance(payload[field], str) and payload[field].strip():
            setattr(user, field, payload[field].strip()[:120])
    user_settings = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if user_settings is None:
        user_settings = UserSettings(user_id=user.id)
        db.add(user_settings)
    if "timezone" in payload and isinstance(payload["timezone"], str) and payload["timezone"].strip():
        user_settings.timezone = payload["timezone"].strip()[:64]
    if "locale" in payload and isinstance(payload["locale"], str) and payload["locale"].strip():
        user_settings.locale = payload["locale"].strip()[:16]
    db.commit()
    return get_account(user, db)


@router.post("/change-password")
def change_password(
    payload: dict,
    user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    current_password = str(payload.get("current_password") or "")
    new_password = str(payload.get("new_password") or "")
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    try:
        validate_password(new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    db.commit()
    return {"status": "password_updated"}


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user:
        token = new_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_digest(token), expires_at=expires_in(settings.password_reset_ttl_minutes)))
        db.commit()
        if settings.app_env == "development":
            return {"status": "accepted", "development_token": token}
    return {"status": "accepted"}


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirm, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_digest(payload.token), PasswordResetToken.used_at.is_(None)))
    if not reset or is_expired(reset.expires_at):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = db.get(User, reset.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = utcnow()
    reset.used_at = utcnow()
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))):
        session.revoked_at = utcnow()
    db.commit()
    _clear_auth_cookies(response)
    return {"status": "password_updated"}
