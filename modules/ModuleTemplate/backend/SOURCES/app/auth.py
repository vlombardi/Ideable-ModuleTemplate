import json
import os
from functools import lru_cache
from typing import Any, Callable

import jwt
import requests
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import OAuth2AuthorizationCodeBearer

AUTHENTIK_JWKS_URL = os.getenv('AUTHENTIK_JWKS_URL', '')


def _derive_oauth2_base_url() -> str:
    authority = (os.getenv('VITE_OIDC_AUTHORITY') or '').strip()
    if '/application/o/' in authority:
        return authority.split('/application/o/', 1)[0]
    return authority.rstrip('/')


_oauth2_base_url = _derive_oauth2_base_url()
_oauth2_authorization_url = (
    f'{_oauth2_base_url}/application/o/authorize/'
    if _oauth2_base_url
    else 'http://localhost:9000/application/o/authorize/'
)
_oauth2_token_url = (
    f'{_oauth2_base_url}/application/o/token/'
    if _oauth2_base_url
    else 'http://localhost:9000/application/o/token/'
)

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=_oauth2_authorization_url,
    tokenUrl=_oauth2_token_url,
    auto_error=False,
)


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


def get_claims(
    authorization: str | None = Header(default=None),
    oauth2_token: str | None = Security(oauth2_scheme),
) -> dict[str, Any]:
    if oauth2_token:
        authorization = f'Bearer {oauth2_token}'
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


def _collect_string_values(value: Any) -> set[str]:
    collected: set[str] = set()
    if value is None:
        return collected
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            collected.add(stripped)
        return collected
    if isinstance(value, dict):
        for nested in value.values():
            collected.update(_collect_string_values(nested))
        return collected
    if isinstance(value, (list, tuple, set)):
        for item in value:
            collected.update(_collect_string_values(item))
        return collected
    return collected


def _get_permissions_from_claims(claims: dict[str, Any]) -> set[str]:
    permission_values: set[str] = set()
    for claim_name, claim_value in (claims or {}).items():
        if not isinstance(claim_name, str):
            continue

        normalized_claim_name = claim_name.lower()
        if (
            normalized_claim_name in {'permissions', 'permission', 'roles', 'role', 'groups', 'group', 'claims', 'entitlements'}
            or normalized_claim_name.endswith('.permissions')
            or normalized_claim_name.endswith('.permission')
            or normalized_claim_name.endswith('.roles')
            or normalized_claim_name.endswith('.role')
            or normalized_claim_name.endswith('.groups')
            or normalized_claim_name.endswith('.group')
            or normalized_claim_name.endswith('.claims')
            or normalized_claim_name.endswith('.entitlements')
            or normalized_claim_name.endswith('.menu_access')
            or normalized_claim_name.endswith('.company_ids')
        ):
            permission_values.update(_collect_string_values(claim_value))

    return permission_values


def require_permission(permission_name: str) -> Callable[[str | None], str]:
    def _dependency(
        claims: dict[str, Any] = Depends(get_claims),
    ) -> str:
        username = (
            claims.get('preferred_username')
            or claims.get('azp')
            or claims.get('client_id')
            or claims.get('sub')
        )
        if not username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='No username claim found')

        permissions = _get_permissions_from_claims(claims)
        if permission_name not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not enough permissions')

        return str(username)

    return _dependency
