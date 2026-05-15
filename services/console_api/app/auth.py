"""Simple JWT auth — single admin user for the MVP.

Per CLAUDE.md, the production swap is the university SSO. The interface
here is just `issue_token(...)` + a FastAPI dependency `require_admin`
that protects state-mutating routes (currently only `PUT /rules`).
"""

from __future__ import annotations

import time
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from .settings import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def issue_token(username: str) -> TokenResponse:
    now = int(time.time())
    exp = now + settings.jwt_ttl_minutes * 60
    payload = {"sub": username, "role": "admin", "iat": now, "exp": exp}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return TokenResponse(access_token=token, expires_in=settings.jwt_ttl_minutes * 60)


def verify_credentials(username: str, password: str) -> bool:
    # Constant-time-ish compare via tuple comparison; single hardcoded user.
    return (username, password) == (settings.admin_username, settings.admin_password)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_admin(token: Annotated[str | None, Depends(oauth2_scheme)]) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_token(token)
    if claims.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin only"
        )
    return claims


__all__ = [
    "LoginRequest",
    "TokenResponse",
    "decode_token",
    "issue_token",
    "require_admin",
    "verify_credentials",
]
