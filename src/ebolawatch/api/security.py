"""API keys, roles and client identification.

Keys are random 32-byte tokens shown once; only an HMAC-SHA256 (keyed with
EW_SECRET_KEY) is stored. Public endpoints need no key. Administrative
endpoints require a role and are audit-logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.base import utcnow
from ..db.models import ApiKey
from ..domain.enums import ROLE_RANK, Role
from .deps import get_session

PREFIX_LEN = 8


def _digest(token: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_key(session: Session, name: str, role: str) -> str:
    Role(role)
    token = "ew_" + secrets.token_urlsafe(32)
    session.add(ApiKey(name=name[:128], role=role, key_prefix=token[:PREFIX_LEN + 3], key_hash=_digest(token)))
    session.flush()
    return token


def lookup(session: Session, token: str | None) -> ApiKey | None:
    if not token or not token.startswith("ew_") or len(token) > 200:
        return None
    for k in session.scalars(select(ApiKey).where(ApiKey.key_prefix == token[:PREFIX_LEN + 3], ApiKey.revoked_at.is_(None))):
        if hmac.compare_digest(k.key_hash, _digest(token)):
            k.last_used_at = utcnow()
            return k
    return None


def require_role(minimum: Role):
    def dep(x_api_key: str | None = Header(default=None, alias="X-API-Key"), session: Session = Depends(get_session)) -> ApiKey:
        key = lookup(session, x_api_key)
        if key is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "valid API key required")
        if ROLE_RANK[Role(key.role)] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role '{minimum.value}' or higher required")
        return key

    return dep


def client_id(request: Request) -> str:
    """Pseudonymous client identifier for rate limiting (IP addresses are not stored)."""
    ip = request.client.host if request.client else "unknown"
    if get_settings().trust_forwarded_for:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            ip = fwd.split(",")[0].strip()
    return hmac.new(get_settings().pseudonym_salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:24]
