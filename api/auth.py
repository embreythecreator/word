import hmac
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from open_notebook.utils.encryption import get_secret_from_env


def get_api_bearer_tokens() -> list[str]:
    """Configured bearer tokens accepted by the REST API."""
    tokens = [
        get_secret_from_env("OPEN_NOTEBOOK_WARD_TOKEN"),
        get_secret_from_env("WARD_TOKEN"),
        get_secret_from_env("API_SERVER_KEY"),
        get_secret_from_env("OPEN_NOTEBOOK_PASSWORD"),
    ]
    return [token for token in tokens if token]


def is_auth_enabled() -> bool:
    return bool(get_api_bearer_tokens())


def _is_valid_bearer_token(credentials: str) -> bool:
    return any(
        hmac.compare_digest(credentials, token)
        for token in get_api_bearer_tokens()
    )


class PasswordAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to check bearer authentication for all API requests.

    Accepts Ward/API server tokens first, then the legacy OPEN_NOTEBOOK_PASSWORD
    token for local deployments. Supports Docker secrets via *_FILE variants.
    """

    def __init__(self, app, excluded_paths: Optional[list] = None):
        super().__init__(app)
        self.excluded_paths = excluded_paths or [
            "/",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    async def dispatch(self, request: Request, call_next):
        # Skip authentication if no token is configured.
        if not is_auth_enabled():
            return await call_next(request)

        # Skip authentication for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # Skip authentication for CORS preflight requests (OPTIONS)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check authorization header
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Expected format: "Bearer {token}"
        try:
            scheme, credentials = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                raise ValueError("Invalid authentication scheme")
        except ValueError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authorization header format"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check configured Ward/password bearer tokens.
        if not _is_valid_bearer_token(credentials):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid bearer token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Bearer token is correct, proceed with the request.
        response = await call_next(request)
        return response


# Optional: HTTPBearer security scheme for OpenAPI documentation
security = HTTPBearer(auto_error=False)


def check_api_password(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> bool:
    """
    Utility function to check API bearer auth.
    Can be used as a dependency in individual routes if needed.
    Supports Docker secrets via *_FILE variants.
    Returns True without checking credentials if no auth token is configured.
    Raises 401 if credentials are missing or don't match a configured token.
    """
    # No token configured - skip authentication.
    if not is_auth_enabled():
        return True

    # No credentials provided
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check bearer token.
    if not _is_valid_bearer_token(credentials.credentials):
        raise HTTPException(
            status_code=401,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True
