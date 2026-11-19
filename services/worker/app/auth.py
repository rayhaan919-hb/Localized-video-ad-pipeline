"""Multi-tenant authentication, JWT verification, session rotation, and workspace RBAC."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import smtplib
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import (
    AuthSession,
    User,
    Workspace,
    WorkspaceMember,
    create_workspace_for_user,
    get_session,
    utcnow,
)
from app.security import get_client_ip, log_audit_event

ACCESS_COOKIE_NAME = "lva_access_token"
REFRESH_COOKIE_NAME = "lva_refresh_token"
OAUTH_STATE_COOKIE_NAME = "lva_oauth_state"

_PBKDF2_ITERATIONS = 260_000
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ROLE_RANK = {"member": 1, "admin": 2, "owner": 3}

_BLOCKED_EMAIL_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "guerrillamail.org",
        "10minutemail.com",
        "tempmail.com",
        "temp-mail.org",
        "yopmail.com",
        "trashmail.com",
        "sharklasers.com",
        "throwaway.email",
        "fakeinbox.com",
        "dispostable.com",
        "getnada.com",
        "maildrop.cc",
        "burnermail.io",
        "mailnesia.com",
        "mohmal.com",
        "example.com",
        "example.org",
        "example.net",
        "test.com",
        "fake.com",
        "invalid.com",
        "localhost",
    }
)
_BLOCKED_EMAIL_TLDS = (".invalid", ".local", ".test", ".localhost", ".example")

# Constant dummy hash for timing equalization when an email does not exist.
_DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$260000$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)


class AuthError(Exception):
    """Base authentication/authorization failure."""


class EmailAlreadyRegisteredError(AuthError):
    """Raised when registering an email that already exists."""


class AccountLockedError(AuthError):
    """Raised when a user exceeds failed login attempts within the lockout window."""


class InvalidCredentialsError(AuthError):
    """Raised for bad email/password or invalid tokens."""


class EmailNotVerifiedError(AuthError):
    """Raised when login is attempted prior to email address verification."""


class GoogleOAuthError(AuthError):
    """Raised when Google OAuth state, exchange, or identity validation fails."""


class GoogleOAuthConfigError(GoogleOAuthError):
    """Raised when Google OAuth client credentials are not configured."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(val: str) -> bytes:
    padding = "=" * (-len(val) % 4)
    return base64.urlsafe_b64decode(val + padding)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sha256_token(raw_token: str) -> str:
    """Hash an opaque token (refresh/reset/verify) with SHA-256 for storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    """Hash a user password using PBKDF2-HMAC-SHA256 with a 16-byte random salt."""
    if len(password) < 8 or len(password) > 128:
        raise ValueError("Password must be between 8 and 128 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt_b64}${digest_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2-HMAC-SHA256 hash in constant time."""
    try:
        scheme, iter_str, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def create_access_token(user: User) -> str:
    """Mint a short-lived HS256 JWT for the authenticated user."""
    secret = settings.effective_auth_jwt_secret
    if not secret:
        raise RuntimeError("AUTH_JWT_SECRET is not configured.")
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "is_admin": bool(user.is_admin),
        "type": "access",
        "iss": "localized-video-ad-worker",
        "iat": now,
        "exp": now + int(settings.ACCESS_TOKEN_TTL_SECONDS),
        "jti": str(uuid.uuid4()),
    }
    signing_input = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def _verify_hs256_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidCredentialsError("Malformed JWT token.")
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        sig = _b64url_decode(sig_b64)
    except Exception as exc:
        raise InvalidCredentialsError("Malformed JWT encoding.") from exc

    if header.get("alg") != "HS256":
        raise InvalidCredentialsError("Unsupported JWT signing algorithm.")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        raise InvalidCredentialsError("Invalid JWT signature.")

    now = int(time.time())
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or int(exp) <= now:
        raise InvalidCredentialsError("JWT token has expired.")

    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate either a native worker JWT or a configured Supabase JWT."""
    worker_secret = settings.effective_auth_jwt_secret
    if worker_secret:
        try:
            payload = _verify_hs256_jwt(token, worker_secret)
            if payload.get("type") == "access" and payload.get("sub"):
                return payload
        except InvalidCredentialsError:
            pass

    supa_secret = settings.effective_supabase_jwt_secret
    if supa_secret:
        payload = _verify_hs256_jwt(token, supa_secret)
        if payload.get("sub") and payload.get("role") in ("authenticated", "service_role", None):
            return payload

    raise InvalidCredentialsError("Invalid or expired access token.")


def normalize_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not cleaned or len(cleaned) > 320 or not _EMAIL_RE.match(cleaned):
        raise ValueError("Please provide a valid email address.")
    return cleaned


def validate_registration_email(email: str) -> str:
    """Validate format and reject fake or disposable email domains outside unit-test mode."""
    norm_email = normalize_email(email)
    if settings.effective_app_env == "test":
        return norm_email
    domain = norm_email.rsplit("@", 1)[-1]
    if (
        domain in _BLOCKED_EMAIL_DOMAINS
        or any(domain.endswith(f".{blocked}") for blocked in _BLOCKED_EMAIL_DOMAINS)
        or any(domain.endswith(tld) for tld in _BLOCKED_EMAIL_TLDS)
    ):
        raise ValueError(
            "Disposable or fake email addresses are not allowed. "
            "Use a real email address or continue with Google."
        )
    return norm_email


def send_verification_email(to_email: str, token: str) -> bool:
    """Deliver a real verification email when SMTP is configured."""
    if not settings.is_smtp_configured:
        return False
    base_url = settings.effective_frontend_app_url or "http://localhost:3000"
    verify_url = f"{base_url}/?verify_token={token}"
    msg = EmailMessage()
    msg["Subject"] = "Verify your Localized Video Ad Studio email"
    msg["From"] = settings.effective_smtp_from_email
    msg["To"] = to_email
    msg.set_content(
        "Welcome to Localized Video Ad Studio!\n\n"
        f"Click to verify your email address:\n{verify_url}\n\n"
        f"Or paste this verification code in the app:\n{token}\n"
    )
    with smtplib.SMTP(
        settings.effective_smtp_host, settings.effective_smtp_port, timeout=15
    ) as server:
        if settings.effective_smtp_use_tls:
            server.starttls()
        if settings.effective_smtp_user:
            server.login(settings.effective_smtp_user, settings.effective_smtp_password)
        server.send_message(msg)
    return True


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    full_name: str = "",
) -> tuple[User, Workspace, str]:
    """Register a new SaaS user, create their isolated workspace, and mint verify token."""
    norm_email = validate_registration_email(email)
    existing = session.scalar(select(User).where(User.email == norm_email))
    if existing is not None:
        raise EmailAlreadyRegisteredError("An account with this email already exists.")

    pw_hash = hash_password(password)
    verify_raw = secrets.token_urlsafe(32)
    now = utcnow()
    user = User(
        id=str(uuid.uuid4()),
        email=norm_email,
        password_hash=pw_hash,
        full_name=(full_name.strip() or norm_email.split("@")[0])[:200],
        is_email_verified=False,
        auth_provider="password",
        email_verify_token_hash=sha256_token(verify_raw),
        email_verify_expires_at=now + timedelta(seconds=int(settings.EMAIL_VERIFY_TTL_SECONDS)),
        failed_login_attempts=0,
        is_admin=False,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()

    workspace_label = f"{user.full_name}'s Workspace" if user.full_name else "My Workspace"
    workspace = create_workspace_for_user(
        session,
        owner_id=user.id,
        name=workspace_label,
        grant_initial_promo=settings.effective_initial_promo_credits > 0,
        promo_credits=settings.effective_initial_promo_credits,
    )
    return user, workspace, verify_raw


def verify_user_email(session: Session, token: str) -> User:
    """Validate email verification token and mark user verified."""
    token_hash = sha256_token(token.strip())
    user = session.scalar(select(User).where(User.email_verify_token_hash == token_hash))
    if user is None:
        raise InvalidCredentialsError("Invalid or expired email verification token.")
    exp = _as_utc(user.email_verify_expires_at)
    if exp is None or exp <= utcnow():
        raise InvalidCredentialsError("Email verification token has expired.")

    user.is_email_verified = True
    user.email_verify_token_hash = None
    user.email_verify_expires_at = None
    user.updated_at = utcnow()
    session.flush()
    return user


def request_password_reset(session: Session, email: str) -> tuple[User | None, str | None]:
    """Generate a single-use password reset token hash if the account exists."""
    norm_email = normalize_email(email)
    user = session.scalar(select(User).where(User.email == norm_email))
    if user is None:
        return None, None
    raw_token = secrets.token_urlsafe(32)
    user.password_reset_token_hash = sha256_token(raw_token)
    user.password_reset_expires_at = utcnow() + timedelta(
        seconds=int(settings.PASSWORD_RESET_TTL_SECONDS)
    )
    user.updated_at = utcnow()
    session.flush()
    return user, raw_token


def confirm_password_reset(session: Session, token: str, new_password: str) -> User:
    """Reset password with a valid token and revoke all existing refresh sessions."""
    token_hash = sha256_token(token.strip())
    user = session.scalar(select(User).where(User.password_reset_token_hash == token_hash))
    if user is None:
        raise InvalidCredentialsError("Invalid or expired password reset token.")
    exp = _as_utc(user.password_reset_expires_at)
    if exp is None or exp <= utcnow():
        raise InvalidCredentialsError("Password reset token has expired.")

    user.password_hash = hash_password(new_password)
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    user.updated_at = utcnow()
    session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    session.flush()
    return user


def authenticate_user(session: Session, *, email: str, password: str) -> User:
    """Authenticate email/password with brute-force lockout protection."""
    norm_email = normalize_email(email)
    user = session.scalar(select(User).where(User.email == norm_email))
    if user is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError("Invalid email or password.")

    now = utcnow()
    locked_until = _as_utc(user.locked_until)
    if locked_until is not None and locked_until > now:
        raise AccountLockedError("Too many failed login attempts. Please try again later.")

    if not verify_password(password, user.password_hash):
        attempts = int(user.failed_login_attempts or 0) + 1
        user.failed_login_attempts = attempts
        if attempts >= int(settings.AUTH_LOCKOUT_MAX_ATTEMPTS):
            user.locked_until = now + timedelta(seconds=int(settings.AUTH_LOCKOUT_WINDOW_SECONDS))
        user.updated_at = now
        session.commit()
        raise InvalidCredentialsError("Invalid email or password.")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.updated_at = now
    session.flush()

    if settings.effective_require_email_verification and not user.is_email_verified:
        raise EmailNotVerifiedError(
            "Please verify your email address before signing in, or continue with Google."
        )

    return user


def issue_session_tokens(
    session: Session,
    user: User,
    *,
    user_agent: str = "",
    ip_address: str = "",
) -> dict[str, Any]:
    """Create a persisted refresh session and return access + refresh token pair."""
    access_token = create_access_token(user)
    refresh_raw = secrets.token_urlsafe(48)
    now = utcnow()
    auth_sess = AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        refresh_token_hash=sha256_token(refresh_raw),
        user_agent=user_agent[:512],
        ip_address=ip_address[:64],
        expires_at=now + timedelta(seconds=int(settings.REFRESH_TOKEN_TTL_SECONDS)),
        created_at=now,
    )
    session.add(auth_sess)
    session.flush()
    return {
        "access_token": access_token,
        "refresh_token": refresh_raw,
        "token_type": "bearer",
        "expires_in": int(settings.ACCESS_TOKEN_TTL_SECONDS),
    }


def rotate_refresh_session(
    session: Session,
    refresh_token: str,
    *,
    user_agent: str = "",
    ip_address: str = "",
) -> tuple[User, dict[str, Any]]:
    """Rotate refresh token cleanly; revoke all user sessions on token replay detection."""
    token_hash = sha256_token(refresh_token.strip())
    existing = session.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    if existing is None:
        raise InvalidCredentialsError("Invalid refresh token.")

    if existing.revoked_at is not None:
        # Refresh token reuse indicates theft: revoke all sessions for that account.
        session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == existing.user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        session.commit()
        raise InvalidCredentialsError("Refresh session revoked due to reuse detection.")

    exp = _as_utc(existing.expires_at)
    if exp is None or exp <= utcnow():
        existing.revoked_at = utcnow()
        session.commit()
        raise InvalidCredentialsError("Refresh session expired.")

    user = session.get(User, existing.user_id)
    if user is None:
        raise InvalidCredentialsError("User no longer exists.")

    existing.revoked_at = utcnow()
    tokens = issue_session_tokens(session, user, user_agent=user_agent, ip_address=ip_address)
    return user, tokens


def revoke_refresh_session(session: Session, refresh_token: str | None) -> None:
    """Revoke the provided refresh token session cleanly."""
    if not refresh_token or not refresh_token.strip():
        return
    token_hash = sha256_token(refresh_token.strip())
    existing = session.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == token_hash)
    )
    if existing is not None and existing.revoked_at is None:
        existing.revoked_at = utcnow()
        session.flush()


def revoke_all_user_sessions(session: Session, user_id: str) -> int:
    """Revoke every active refresh session belonging to user_id."""
    uid_str = str(uuid.UUID(str(user_id)))
    now = utcnow()
    res = session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == uid_str, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    session.flush()
    return int(res.rowcount or 0)


def extract_bearer_or_cookie_token(request: Request) -> str | None:
    """Read JWT access token from Authorization header or HttpOnly session cookie."""
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header:
        parts = auth_header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    cookie_token = request.cookies.get(ACCESS_COOKIE_NAME, "").strip()
    if cookie_token:
        return cookie_token
    return None


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """Authenticate caller from verified JWT and return User row; fail closed with 401."""
    token = extract_bearer_or_cookie_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(token)
        user_id = str(uuid.UUID(str(claims["sub"])))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user record not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    locked_until = _as_utc(user.locked_until)
    if locked_until is not None and locked_until > utcnow():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is temporarily locked due to repeated security failures.",
        )
    return user


def require_worker_api_key_if_configured(request: Request) -> None:
    """Validate internal service-to-service key when present or required in production."""
    configured = settings.effective_worker_api_key
    if not configured:
        if settings.is_production:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Worker internal key is not configured.",
            )
        return
    supplied = request.headers.get("x-worker-api-key", "").strip()
    if not supplied or not hmac.compare_digest(supplied, configured):
        log_audit_event(
            "worker_api_key_rejected",
            level="WARNING",
            ip_address=get_client_ip(request),
            details={"path": request.url.path},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing worker service API key.",
        )


def require_internal_service_key(request: Request) -> None:
    """Strictly require WORKER_API_KEY even in development for internal/admin service routes."""
    configured = settings.effective_worker_api_key
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal service authentication key is not configured.",
        )
    supplied = request.headers.get("x-worker-api-key", "").strip()
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal service API key.",
        )


def require_workspace_role(
    session: Session,
    *,
    workspace_id: str,
    user: User,
    minimum_role: str = "member",
) -> tuple[Workspace, WorkspaceMember]:
    """Enforce server-side workspace membership and RBAC role hierarchy."""
    if minimum_role not in _ROLE_RANK:
        raise ValueError(f"Unknown role requirement: {minimum_role}")
    try:
        ws_uuid = str(uuid.UUID(str(workspace_id)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="workspace_id must be a valid UUID.") from exc

    workspace = session.get(Workspace, ws_uuid)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    membership = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws_uuid,
            WorkspaceMember.user_id == user.id,
        )
    )
    if membership is None:
        log_audit_event(
            "workspace_access_denied",
            level="WARNING",
            user_id=user.id,
            workspace_id=ws_uuid,
            details={"reason": "not_a_member"},
        )
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this workspace.",
        )

    if _ROLE_RANK.get(membership.role, 0) < _ROLE_RANK[minimum_role]:
        raise HTTPException(
            status_code=403,
            detail=f"Requires workspace role '{minimum_role}' or higher.",
        )

    return workspace, membership


def build_google_oauth_start(mode: str = "login") -> tuple[str, str]:
    """Build a Google OAuth 2.0 Authorization Code + PKCE URL and signed state cookie."""
    if not settings.is_google_oauth_configured:
        raise GoogleOAuthConfigError(
            "Google Sign-In requires GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET."
        )
    secret = settings.effective_auth_jwt_secret
    if not secret:
        raise GoogleOAuthConfigError("AUTH_JWT_SECRET is required for OAuth state signing.")

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(48)
    code_challenge = _b64url_encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
    clean_mode = "register" if mode == "register" else "login"

    payload_dict = {
        "state": state,
        "code_verifier": code_verifier,
        "mode": clean_mode,
        "exp": int(time.time()) + 600,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
    )
    sig_hex = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    signed_cookie = f"{payload_b64}.{sig_hex}"

    query = urlencode(
        {
            "client_id": settings.effective_google_oauth_client_id,
            "redirect_uri": settings.effective_google_oauth_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}", signed_cookie


def verify_google_oauth_state_cookie(cookie_value: str, expected_state: str) -> dict[str, Any]:
    """Verify signed lva_oauth_state cookie integrity, expiry, and matching CSRF state."""
    secret = settings.effective_auth_jwt_secret
    if not secret or not cookie_value or "." not in cookie_value or not expected_state:
        raise GoogleOAuthError("Missing or invalid OAuth state cookie.")

    payload_b64, sig_hex = cookie_value.strip().split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig_hex.strip(), expected_sig):
        raise GoogleOAuthError("Invalid OAuth state signature.")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise GoogleOAuthError("Malformed OAuth state payload.") from exc

    exp = int(payload.get("exp") or 0)
    if exp <= int(time.time()):
        raise GoogleOAuthError("OAuth login session expired. Please try again.")

    stored_state = str(payload.get("state") or "")
    if not stored_state or not hmac.compare_digest(stored_state, expected_state.strip()):
        raise GoogleOAuthError("OAuth CSRF state mismatch.")
    return payload


def exchange_google_oauth_code(*, code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange Google authorization code for verified OpenID Connect user identity."""
    if not settings.is_google_oauth_configured:
        raise GoogleOAuthConfigError("Google OAuth client credentials are not configured.")

    client_id = settings.effective_google_oauth_client_id
    client_secret = settings.effective_google_oauth_client_secret
    redirect_uri = settings.effective_google_oauth_redirect_uri

    try:
        with httpx.Client(timeout=15.0) as client:
            token_resp = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
            )
            if token_resp.status_code != 200:
                raise GoogleOAuthError(
                    f"Google token exchange failed ({token_resp.status_code})."
                )
            token_data = token_resp.json()
            access_token = str(token_data.get("access_token") or "").strip()
            id_token = str(token_data.get("id_token") or "").strip()
            if not access_token:
                raise GoogleOAuthError("Google token response lacked access_token.")

            id_claims: dict[str, Any] = {}
            if id_token and len(id_token.split(".")) == 3:
                try:
                    id_claims = json.loads(_b64url_decode(id_token.split(".")[1]).decode("utf-8"))
                except Exception as exc:
                    raise GoogleOAuthError("Malformed Google id_token payload.") from exc
                if str(id_claims.get("aud") or "") != client_id:
                    raise GoogleOAuthError("Google id_token audience mismatch.")
                if str(id_claims.get("iss") or "") not in (
                    "https://accounts.google.com",
                    "accounts.google.com",
                ):
                    raise GoogleOAuthError("Google id_token issuer mismatch.")

            info_resp = client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_resp.status_code != 200:
                raise GoogleOAuthError("Failed to fetch verified Google user profile.")
            userinfo = info_resp.json()
    except GoogleOAuthError:
        raise
    except httpx.HTTPError as exc:
        raise GoogleOAuthError(f"Could not contact Google OAuth endpoints: {exc}") from exc

    sub = str(userinfo.get("sub") or "").strip()
    raw_email = str(userinfo.get("email") or "").strip()
    email_verified = userinfo.get("email_verified") is True
    if not sub or not raw_email:
        raise GoogleOAuthError("Google account did not provide required subject/email.")
    if not email_verified:
        raise GoogleOAuthError("Your Google account email is not verified.")
    if id_claims.get("sub") and not hmac.compare_digest(str(id_claims["sub"]), sub):
        raise GoogleOAuthError("Google identity subject mismatch.")

    return {
        "sub": sub,
        "email": normalize_email(raw_email),
        "name": str(userinfo.get("name") or "").strip()[:200],
    }


def upsert_google_user(
    session: Session,
    *,
    google_sub: str,
    email: str,
    full_name: str = "",
) -> tuple[User, Workspace, bool]:
    """Sign in existing user (linking google_sub) or create a verified Google SaaS user."""
    norm_email = normalize_email(email)
    user = session.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = session.scalar(select(User).where(User.email == norm_email))

    now = utcnow()
    if user is not None:
        user.google_sub = google_sub
        user.is_email_verified = True
        user.email_verify_token_hash = None
        user.email_verify_expires_at = None
        if user.auth_provider == "password":
            user.auth_provider = "google+password"
        elif user.auth_provider not in ("google", "google+password"):
            user.auth_provider = "google"
        if not user.full_name and full_name:
            user.full_name = full_name[:200]
        user.updated_at = now
        session.flush()

        primary_ws = session.scalar(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.created_at.asc())
        )
        if primary_ws is None:
            ws_label = f"{user.full_name}'s Workspace" if user.full_name else "My Workspace"
            primary_ws = create_workspace_for_user(
                session,
                owner_id=user.id,
                name=ws_label,
                grant_initial_promo=False,
                promo_credits=0,
            )
        return user, primary_ws, False

    display_name = (full_name.strip() or norm_email.split("@")[0])[:200]
    user = User(
        id=str(uuid.uuid4()),
        email=norm_email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        full_name=display_name,
        is_email_verified=True,
        auth_provider="google",
        google_sub=google_sub,
        failed_login_attempts=0,
        is_admin=False,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.flush()

    workspace_label = f"{display_name}'s Workspace" if display_name else "My Workspace"
    workspace = create_workspace_for_user(
        session,
        owner_id=user.id,
        name=workspace_label,
        grant_initial_promo=settings.effective_initial_promo_credits > 0,
        promo_credits=settings.effective_initial_promo_credits,
    )
    return user, workspace, True
