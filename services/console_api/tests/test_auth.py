"""Auth-flow tests — happy path + bad credentials + missing token + admin gate."""

import jwt
import pytest

from services.console_api.app.auth import (
    decode_token,
    issue_token,
    require_admin,
    verify_credentials,
)
from services.console_api.app.settings import settings


def test_credentials_happy_path():
    assert verify_credentials(settings.admin_username, settings.admin_password)


def test_credentials_rejected():
    assert not verify_credentials("admin", "wrong")
    assert not verify_credentials("not-admin", settings.admin_password)


def test_token_round_trip():
    tok = issue_token("admin")
    claims = decode_token(tok.access_token)
    assert claims["sub"] == "admin"
    assert claims["role"] == "admin"
    assert claims["exp"] > claims["iat"]


def test_token_with_wrong_secret_rejected():
    from fastapi import HTTPException

    bad = jwt.encode({"sub": "admin", "role": "admin"},
                     "different-secret",
                     algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as ex:
        decode_token(bad)
    assert ex.value.status_code == 401


def test_require_admin_rejects_missing_token():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ex:
        require_admin(None)
    assert ex.value.status_code == 401


def test_require_admin_rejects_non_admin_role():
    from fastapi import HTTPException

    tok = jwt.encode({"sub": "viewer", "role": "viewer"},
                     settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as ex:
        require_admin(tok)
    assert ex.value.status_code == 403


def test_require_admin_accepts_valid_admin():
    tok = issue_token("admin")
    claims = require_admin(tok.access_token)
    assert claims["role"] == "admin"
