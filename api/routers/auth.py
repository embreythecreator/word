"""
Authentication router for Open Notebook API.
Provides endpoints to check authentication status.
"""

from fastapi import APIRouter

from api.auth import is_auth_enabled

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
async def get_auth_status():
    """
    Check if authentication is enabled.
    Returns whether a bearer token is required to access the API.
    Supports Ward/API server tokens and the legacy OPEN_NOTEBOOK_PASSWORD token.
    """
    auth_enabled = is_auth_enabled()

    return {
        "auth_enabled": auth_enabled,
        "message": "Bearer authentication is required"
        if auth_enabled
        else "Authentication is disabled",
    }
