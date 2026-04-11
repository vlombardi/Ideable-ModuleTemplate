import json
import os
from functools import lru_cache
from typing import Any, Callable

import jwt
import requests
from fastapi import Depends, Header, HTTPException, status

AUTHENTIK_JWKS_URL = os.getenv('AUTHENTIK_JWKS_URL', '')
HOSTAPP_API_URL = os.getenv('HOSTAPP_API_URL', 'http://hostapp-backend:8001')


def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Missing bearer token')
    return authorization.replace('Bearer ', '', 1)


@lru_cache(maxsize=1)
def _get_jwks() -> dict[str, Any]:
    if not AUTHENTIK_JWKS_URL:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='AUTHENTIK_JWKS_URL not configured')
    response = requests.get(AUTHENTIK_JWKS_URL, timeout=10)
    response.raise_for_status()
    return response.json()


def _validate_token(token: str) -> dict[str, Any]:
    jwks = _get_jwks()
    unverified_header = jwt.get_unverified_header(token)

    rsa_key = None
    for key in jwks.get('keys', []):
        if key.get('kid') == unverified_header.get('kid'):
            rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            break

    if rsa_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT signing key not found')

    try:
        return jwt.decode(token, rsa_key, algorithms=['RS256'], options={'verify_aud': False})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f'Invalid token: {exc}') from exc


def get_claims(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _extract_bearer(authorization)
    return _validate_token(token)


def get_username(claims: dict[str, Any] = Depends(get_claims)) -> str:
    username = (
        claims.get('preferred_username')
        or claims.get('azp')
        or claims.get('client_id')
        or claims.get('sub')
    )
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='No username claim found')
    return username


def _get_permissions_from_hostapp(authorization: str) -> set[str]:
    response = requests.get(
        f"{HOSTAPP_API_URL.rstrip('/')}/api/me",
        headers={'Authorization': authorization},
        timeout=10,
    )
    if response.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Unable to resolve permissions from HostApp')

    payload = response.json()
    permissions = payload.get('permissions')
    if permissions is None:
        permissions = payload.get('active_profile_permissions', [])
    if isinstance(permissions, list):
        return {str(p) for p in permissions}
    return set()


def require_permission(permission_name: str) -> Callable[[str | None], str]:
    def _dependency(authorization: str | None = Header(default=None)) -> str:
        token = _extract_bearer(authorization)
        claims = _validate_token(token)
        username = (
            claims.get('preferred_username')
            or claims.get('azp')
            or claims.get('client_id')
            or claims.get('sub')
        )
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='No username claim found')

        permissions = _get_permissions_from_hostapp(authorization or '')
        if permission_name not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not enough permissions')

        return str(username)

    return _dependency
