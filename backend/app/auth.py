from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def require_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    access_token: str | None = Query(None),
    settings: Settings = Depends(get_settings),
) -> None:
    """If API_TOKEN is set, require matching Bearer or ?access_token= (for SSE)."""
    expected = (settings.api_token or "").strip()
    if not expected:
        return
    got = ""
    if creds is not None and creds.scheme.lower() == "bearer":
        got = creds.credentials
    elif access_token:
        got = access_token
    else:
        # also accept header without HTTPBearer parse edge cases
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            got = auth[7:].strip()
    if not got:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    if got != expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid token")
