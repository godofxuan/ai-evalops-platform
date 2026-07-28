from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.errors import APIError
from app.auth.principals import Principal
from app.auth.service import APIKeyLookup, InvalidAPIKeyError, authenticate_api_key

_bearer_scheme = HTTPBearer(auto_error=False)


def get_api_key_lookup(request: Request) -> APIKeyLookup | None:
    lookup: APIKeyLookup | None = request.app.state.api_key_lookup
    return lookup


async def get_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
    lookup: Annotated[APIKeyLookup | None, Depends(get_api_key_lookup)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _invalid_api_key_error()
    if lookup is None:
        raise RuntimeError("API key lookup is not configured")

    try:
        principal = await authenticate_api_key(
            credentials.credentials,
            lookup=lookup,
            now=datetime.now(UTC),
        )
    except InvalidAPIKeyError:
        raise _invalid_api_key_error() from None

    structlog.contextvars.bind_contextvars(
        tenant_id=str(principal.tenant_id),
        api_key_prefix=principal.key_prefix,
    )
    return principal


def _invalid_api_key_error() -> APIError:
    return APIError(
        status_code=401,
        code="invalid_api_key",
        message="Authentication credentials are invalid.",
        headers={"WWW-Authenticate": "Bearer"},
    )
