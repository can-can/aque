from typing import Optional

from fastapi import Header, HTTPException, Query, status

_BEARER = "Bearer "


def token_ok(auth_header: Optional[str], query_token: Optional[str], expected: str) -> bool:
    """True if the bearer header or ?token matches the expected token."""
    if not expected:
        return False
    if auth_header and auth_header.startswith(_BEARER):
        if auth_header[len(_BEARER):] == expected:
            return True
    return query_token is not None and query_token == expected


def make_http_auth(expected: str):
    """Return a FastAPI dependency that 401s when the token is missing/wrong."""
    async def dependency(
        authorization: Optional[str] = Header(default=None),
        token: Optional[str] = Query(default=None),
    ) -> None:
        if not token_ok(authorization, token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
            )
    return dependency
