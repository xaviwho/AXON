"""Auth routes — single hardcoded admin user for the MVP."""

from fastapi import APIRouter, Form, HTTPException, status

from ..auth import LoginRequest, TokenResponse, issue_token, verify_credentials

router = APIRouter(prefix="/auth")


@router.post("/login", response_model=TokenResponse)
async def login(
    # Accept either JSON body (consoles, curl) or form (OAuth2 password flow / Swagger UI).
    username: str = Form(default=""),
    password: str = Form(default=""),
) -> TokenResponse:
    if not verify_credentials(username, password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid credentials")
    return issue_token(username)


@router.post("/login.json", response_model=TokenResponse)
async def login_json(body: LoginRequest) -> TokenResponse:
    if not verify_credentials(body.username, body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid credentials")
    return issue_token(body.username)
