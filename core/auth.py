from typing import Optional

import requests
from starlette.requests import Request

from core.config import SUPABASE_URL, ENV

from models.JWTBearer import (
    JWKS,
    JWTBearer,
    DevBypassBearer,
    JWTAuthorizationCredentials,
)

jwks = JWKS.model_validate(
    requests.get(
        f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    ).json()
)


class UserScopedBearer(DevBypassBearer):
    """Auth dependency that also publishes the caller's id on the request.

    Dependencies that don't receive the credentials object — notably
    `enforce_chat_rate_limit` — read `request.state.user_id`.
    """

    async def __call__(self, request: Request) -> Optional[JWTAuthorizationCredentials]:
        credentials = await super().__call__(request)
        request.state.user_id = credentials.claims.get("sub") if credentials else None
        return credentials


# Single auth dependency: dev bypass in development, strict in production.
# Routes import only `auth` — optional_auth is no longer needed.
auth = UserScopedBearer(jwks, env=ENV)
