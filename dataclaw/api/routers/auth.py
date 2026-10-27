"""Browser login for API token authentication (see dataclaw.api.security)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dataclaw.api import security

router = APIRouter()


class LoginRequest(BaseModel):
    token: str


@router.get("/status")
async def auth_status(request: Request) -> dict[str, Any]:
    required = security.token_required()
    return {
        "auth_required": required,
        "authenticated": not required or security.is_authenticated(request),
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> JSONResponse:
    if not security.token_matches(body.token):
        return JSONResponse({"detail": "Invalid token"}, status_code=401)
    response = JSONResponse({"authenticated": True})
    security.set_auth_cookie(
        response, security.api_token(), secure=request.url.scheme == "https"
    )
    return response


@router.post("/logout")
async def logout() -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    security.clear_auth_cookie(response)
    return response
