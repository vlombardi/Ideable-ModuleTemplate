import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, NamedTuple

import jwt
import requests
from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import OAuth2AuthorizationCodeBearer

logger = logging.getLogger(__name__)

AUTHENTIK_JWKS_URL = os.getenv('AUTHENTIK_JWKS_URL', '')

# How long a fetched JWKS stays fresh. A rotation is picked up within this window without any
# request failing, because an unknown `kid` also forces a refresh (see _signing_key).
JWKS_TTL_SECONDS = int(os.getenv('AUTHENTIK_JWKS_TTL_SECONDS', '600'))

# A forced refresh (unknown `kid`) may run at most this often, so a flood of tokens signed by a
# key the provider never publishes cannot turn into a JWKS request storm.
JWKS_MIN_REFRESH_INTERVAL_SECONDS = 30

# Bounded retry around the fetch: 3 attempts with exponential backoff, ≤2s of sleeping in total.
JWKS_FETCH_ATTEMPTS = 3
JWKS_FETCH_BACKOFF_SECONDS = (0.5, 1.0)
JWKS_FETCH_TIMEOUT_SECONDS = 5


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


# Signing keys are cached as ready-to-use RSA key objects indexed by `kid`, so a request never
# rebuilds a key from its JWK. `_jwks_lock` serialises refreshes: concurrent misses collapse into
# a single fetch. A token-string cache is deliberately NOT kept — it would be unbounded and would
# keep honouring permissions past the token's `exp`.
_jwks_lock = threading.Lock()
_jwks_cache: dict[str, Any] = {
    'keys': {},           # kid -> RSA public key object
    'fetched_at': None,   # epoch seconds of the last SUCCESSFUL fetch
    'attempted_at': None,  # epoch seconds of the last attempt, successful or not
    'outcome': 'never',   # 'never' | 'ok' | 'error'
    'error': None,        # last failure, as a short string
}


def _fetch_jwks() -> dict[str, Any]:
    """Fetch the JWKS with bounded exponential backoff. Raises `requests` errors on give-up."""
    last_exc: Exception | None = None
    for attempt in range(JWKS_FETCH_ATTEMPTS):
        try:
            response = requests.get(AUTHENTIK_JWKS_URL, timeout=JWKS_FETCH_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 — network/HTTP/JSON all mean "try again"
            last_exc = exc
            if attempt < len(JWKS_FETCH_BACKOFF_SECONDS):
                time.sleep(JWKS_FETCH_BACKOFF_SECONDS[attempt])
    raise last_exc  # type: ignore[misc]


def _provider_unavailable(exc: Exception) -> HTTPException:
    """An unreachable identity provider is a retryable 503, never an opaque 500."""
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f'Identity provider unreachable: {type(exc).__name__}',
        headers={'Retry-After': str(JWKS_MIN_REFRESH_INTERVAL_SECONDS)},
    )


def _refresh_jwks() -> None:
    """Fetch the JWKS and replace the key cache. Caller must hold `_jwks_lock`."""
    if not AUTHENTIK_JWKS_URL:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail='AUTHENTIK_JWKS_URL not configured')
    _jwks_cache['attempted_at'] = time.time()
    try:
        document = _fetch_jwks()
    except Exception as exc:  # noqa: BLE001 — surfaced to the caller as 503
        _jwks_cache['outcome'] = 'error'
        _jwks_cache['error'] = type(exc).__name__
        logger.warning('JWKS refresh failed after %d attempts: %s', JWKS_FETCH_ATTEMPTS, exc)
        raise _provider_unavailable(exc) from exc

    keys: dict[str, Any] = {}
    for key in document.get('keys', []):
        kid = key.get('kid')
        if kid:
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
    _jwks_cache.update({'keys': keys, 'fetched_at': time.time(), 'outcome': 'ok', 'error': None})
    logger.info('JWKS refreshed: %d signing key(s) cached (ttl %ds)', len(keys), JWKS_TTL_SECONDS)


def _signing_key(kid: str | None) -> Any:
    """Return the cached RSA key for `kid`, refreshing when stale or on an unknown `kid`.

    Refresh-on-miss is what makes a provider key rotation self-healing: the first token signed by
    the new key triggers exactly one refresh (rate-limited), instead of every request failing
    until the container is restarted.
    """
    # Fast path — a warm, unexpired cache serves the key with no lock and no crypto work.
    fetched_at = _jwks_cache['fetched_at']
    if fetched_at is not None and (time.time() - fetched_at) < JWKS_TTL_SECONDS:
        key = _jwks_cache['keys'].get(kid)
        if key is not None:
            return key

    with _jwks_lock:
        fetched_at = _jwks_cache['fetched_at']
        expired = fetched_at is None or (time.time() - fetched_at) >= JWKS_TTL_SECONDS
        if expired:
            _refresh_jwks()

        key = _jwks_cache['keys'].get(kid)
        if key is not None or kid is None:
            return key

        # Unknown kid on a fresh cache: the provider may have just rotated. Force one refresh,
        # no more often than JWKS_MIN_REFRESH_INTERVAL_SECONDS.
        attempted_at = _jwks_cache['attempted_at']
        if attempted_at is not None and (time.time() - attempted_at) < JWKS_MIN_REFRESH_INTERVAL_SECONDS:
            return None
        logger.info('Unknown JWT kid %r — forcing a JWKS refresh (possible key rotation)', kid)
        _refresh_jwks()
        return _jwks_cache['keys'].get(kid)


def jwks_cache_state() -> tuple[bool, dict[str, Any]]:
    """Readiness check: report the JWKS cache state **without** forcing a remote fetch.

    The JWKS is fetched lazily on the first token validation, so an empty cache on a freshly
    started backend is not a fault — only a missing `AUTHENTIK_JWKS_URL` is. Returns
    (ok, detail) where detail carries the state plus the last fetch timestamp and outcome, so
    `/ready` shows whether the cache is warm and when it last refreshed.
    """
    if not AUTHENTIK_JWKS_URL:
        return False, {'state': 'unconfigured'}
    fetched_at = _jwks_cache['fetched_at']
    detail = {
        'state': 'ok' if _jwks_cache['keys'] else 'not_cached',
        'keys': len(_jwks_cache['keys']),
        'fetched_at': (
            time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(fetched_at)) if fetched_at else None
        ),
        'last_outcome': _jwks_cache['outcome'],
    }
    if _jwks_cache['error']:
        detail['last_error'] = _jwks_cache['error']
    return True, detail


def _validate_token(token: str) -> dict[str, Any]:
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as exc:
        # A malformed bearer token is a client error: without this it escapes as a 500.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f'Malformed token: {exc}') from exc

    rsa_key = _signing_key(unverified_header.get('kid'))

    if rsa_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT signing key not found')

    try:
        return jwt.decode(token, rsa_key, algorithms=['RS256'], options={'verify_aud': False})
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f'Invalid token: {exc}') from exc


def get_claims(
    request: Request,
    authorization: str | None = Header(default=None),
    oauth2_token: str | None = Security(oauth2_scheme),
) -> dict[str, Any]:
    """Claims of the current request, validated **once**.

    The app-level audit dependency runs before route dependencies and stores the validated claims
    on `request.state`; reading them here removes the second RS256 verification that every
    protected route used to pay. The direct path is kept for requests that never passed the
    app-level dependency (unit tests, sub-applications) and for invalid tokens, which must still
    raise 401 here.
    """
    claims = getattr(request.state, 'claims', None)
    if claims is not None:
        return claims
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


def _username_from_claims(claims: dict[str, Any]) -> str | None:
    username = (
        claims.get('preferred_username')
        or claims.get('azp')
        or claims.get('client_id')
        or claims.get('sub')
    )
    return str(username).strip().lower() if username else None


def authenticate_optional(authorization: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Validate the request's bearer token **once**, returning (claims, username).

    Returns (None, None) for a missing or invalid token — never raises, so it is safe in the
    app-level dependency that also runs on public routes. This is the single validation point of
    a request: the claims it returns are stored on `request.state` and reused by `get_claims`.
    """
    if not authorization or not authorization.startswith('Bearer '):
        return None, None
    token = authorization.replace('Bearer ', '', 1)
    try:
        claims = _validate_token(token)
    except Exception:
        return None, None
    return claims, _username_from_claims(claims)


def _get_current_username_optional(
    authorization: str | None = Header(default=None),
    oauth2_token: str | None = Security(oauth2_scheme),
) -> str | None:
    """Return the current username, or None for unauthenticated requests.

    Unlike get_claims/get_username, this never raises HTTPException.
    Safe for use in app-level dependencies that must run on public routes.
    """
    if oauth2_token:
        authorization = f'Bearer {oauth2_token}'
    return authenticate_optional(authorization)[1]


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


# ---------------------------------------------------------------------------
# Permission resolution
# ---------------------------------------------------------------------------
# The token is THIN: it carries identity and tenant ids, not permissions. A remote module therefore
# asks host_app what the caller may do, because host_app owns the authorization tables.
#
# Two things this is deliberately NOT:
#
# - It is not a call to Authentik. The identity plane is CPU-bound at ~6.3 logins/s and must never
#   sit on the request path. host_app answers from its own tables through a cache validated by a
#   Postgres generation counter.
# - It is not a fallback to the old claim arrays. Reading permissions from a thin token would find
#   none and deny everything, or -- worse, during a rolling upgrade -- find a stale set and honour
#   it. There is one source.
#
# The response is cached per token for `PERMISSION_CACHE_TTL_SECONDS`, which is host_app's published
# revocation SLO: a permission removed upstream stops being honoured here within that window.

HOSTAPP_API_URL = os.getenv('HOSTAPP_API_URL', '').rstrip('/')
PERMISSION_CACHE_TTL_SECONDS = float(os.getenv('PERMISSION_CACHE_TTL_SECONDS', '60'))

# token -> (expires_at_monotonic, Authorization)
_PERMISSION_CACHE: dict[str, tuple[float, 'Authorization']] = {}
_PERMISSION_CACHE_LOCK = threading.Lock()


class PermissionResolutionError(RuntimeError):
    """host_app could not be asked. The caller must deny — there is nothing to fall back on."""


class Authorization(NamedTuple):
    """host_app's answer about one caller: what they may do, and whose data they may do it to."""

    permissions: frozenset[str]
    tenant_ids: frozenset[str]


def _resolve_authorization(token: str) -> Authorization:
    """Ask host_app once for BOTH halves of the authorization answer, and cache them together.

    Tenancy used to arrive separately, as a `hostapp.tenant_ids` claim rendered by Authentik from a
    user attribute that host_app wrote. That made one decision travel two paths of different length:
    permissions were re-resolved every `PERMISSION_CACHE_TTL_SECONDS`, while tenancy was frozen into
    the token until it expired, and stayed whatever it was at login even after an administrator
    moved the user. The projection could also fail silently in the middle, and did -- the attribute
    write cleared host_app's own API permissions, so no admin's tenant claim was ever written and
    every tenant-scoped request here answered 403.

    One call, one cache entry, one revocation window, one thing to be wrong.
    """
    now = time.monotonic()
    with _PERMISSION_CACHE_LOCK:
        cached = _PERMISSION_CACHE.get(token)
        if cached is not None and cached[0] > now:
            return cached[1]

    if not HOSTAPP_API_URL:
        raise PermissionResolutionError('HOSTAPP_API_URL is not configured')

    try:
        response = requests.get(
            f'{HOSTAPP_API_URL}/api/me',
            headers={'Authorization': f'Bearer {token}'},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 — any failure to ask means we cannot decide
        raise PermissionResolutionError(str(exc)) from exc

    resolved = Authorization(
        permissions=frozenset(
            p for p in (payload.get('permissions') or []) if isinstance(p, str)
        ),
        tenant_ids=frozenset(
            str(t) for t in (payload.get('tenant_ids') or []) if t not in (None, '')
        ),
    )
    with _PERMISSION_CACHE_LOCK:
        _PERMISSION_CACHE[token] = (now + PERMISSION_CACHE_TTL_SECONDS, resolved)
    return resolved


def _resolve_permissions(token: str) -> frozenset[str]:
    """The permission half of `_resolve_authorization`."""
    return _resolve_authorization(token).permissions


def invalidate_permission_cache() -> None:
    """Drop this replica's cached resolutions. Used by tests and by an explicit refresh."""
    with _PERMISSION_CACHE_LOCK:
        _PERMISSION_CACHE.clear()


def require_permission(permission_name: str) -> Callable[[str | None], str]:
    def _dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        oauth2_token: str | None = Security(oauth2_scheme),
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

        if oauth2_token:
            authorization = f'Bearer {oauth2_token}'
        token = _extract_bearer(authorization)

        try:
            permissions = _resolve_permissions(token)
        except PermissionResolutionError as exc:
            # Fail-closed, and distinguishably: 503 says "we could not decide", which is a different
            # operational problem from 403's "we decided no".
            logger.error('permission resolution via host_app failed: %s', exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail='Authorization temporarily unavailable',
            ) from exc

        if permission_name not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='Not enough permissions')

        return str(username)

    return _dependency

# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------
# auth-specs.md §5.5 requires tenant scoping on every data access. The template did not implement
# it: no tenancy column, no filter, and the tenant claim flattened in with permissions — so every
# module derived from this scaffold inherited a cross-tenant read.
#
# The scope now comes from host_app's `/api/me`, beside the permissions, not from a token claim.
# Everything here still fails CLOSED. A missing, empty or malformed tenant list denies access rather
# than falling back to "all tenants": a misconfiguration should be an outage, not a breach.


# Entries are `TenantName(ID)` — the canonical wire format, and what host_app sends (`EU(1)`). The
# shape is unchanged by the move off the token, deliberately: parsing only bare integers once made
# every real value unparseable, every id was dropped as non-numeric, and require_tenant_scope denied
# the request. Fail-closed did its job and hid the bug, because a 403 looks the same whether the
# value is missing or unreadable.
_TENANT_TAGGED_RE = re.compile(r'^[^()]*\((\d+)\)$')


def _parse_tenant_id(value: Any) -> int | None:
    """One claim entry as a tenant id, or None if it does not carry one.

    Accepts `TenantName(ID)` (canonical), a bare integer, and a numeric string. The tenant NAME is
    deliberately not used for anything: names are editable labels, ids are the key the data is
    partitioned on, and matching on a name would silently follow a rename into the wrong tenant.
    """
    if isinstance(value, bool):
        return None  # `True` is not tenant 1
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.isdigit():
        return int(text)
    tagged = _TENANT_TAGGED_RE.match(text)
    return int(tagged.group(1)) if tagged else None


def tenant_ids_from(values: Iterable[Any]) -> set[int]:
    """Authorised tenant ids as integers, from whatever host_app reported.

    Accepts `TenantName(ID)`, ints or numeric strings, and drops anything else rather than guessing.
    The tolerant parsing is kept from when these arrived as an Authentik claim: host_app now sends
    one canonical shape, but a value that cannot be read must still be discarded loudly instead of
    becoming a tenant id nobody intended.
    """
    found: set[int] = set()
    for value in values or ():
        tenant_id = _parse_tenant_id(value)
        if tenant_id is None:
            logger.warning('Ignoring unparseable tenant id %r from host_app', value)
            continue
        found.add(tenant_id)
    return found


# The one permission that widens a tenant filter. Declared in config/authorization.yaml and
# granted to host_app's application-wide `admin` profile — NOT to the module's own
# `template_admin`, which administers one tenant's items.
#
# Deliberately a named permission rather than a superadmin branch. An implicit "administrators see
# everything" is invisible three times over: absent from the code path a reviewer reads, absent
# from the token an operator inspects, and absent from the authorization contract an auditor is
# given. It also cannot be granted to one person — whoever later holds the same role inherits it
# silently. And it is a READ permission: see TenantScope.
CROSS_TENANT_READ_PERMISSION = 'template.items:read_all_tenants'


@dataclass(frozen=True)
class TenantScope:
    """Whose data a request may touch — and, separately, whose it may only look at.

    Two fields rather than one widened set, because reading across tenants and writing across
    tenants are different authorisations and only the first is grantable:

    - `tenant_ids` — the caller's own tenants, from the token. Never empty (require_tenant_scope
      refuses that) and never widened, so every WRITE is confined to it whatever else is true.
    - `read_all_tenants` — set only when CROSS_TENANT_READ_PERMISSION is in the token. Widens
      reads, and nothing else.
    """

    tenant_ids: frozenset[int]
    read_all_tenants: bool = False

    def __post_init__(self) -> None:
        # An empty scope must never exist as a value: a caller reading `scope.tenant_ids` cannot
        # tell "no tenants" from "all tenants" by looking at an empty set, and one of those two
        # readings is a breach.
        if not self.tenant_ids:
            raise ValueError('TenantScope requires at least one tenant id')


def require_tenant_scope():
    """Dependency returning the caller's `TenantScope`, or 403.

    Separate from `require_permission`: permission says what may be done, tenant scope says to
    whose data. Both are required on a data endpoint, and neither substitutes for the other.
    """

    def dependency(
        authorization: str | None = Header(default=None),
        oauth2_token: str | None = Security(oauth2_scheme),
        claims: dict[str, Any] = Depends(get_claims),
    ) -> TenantScope:
        if oauth2_token:
            authorization = f'Bearer {oauth2_token}'
        try:
            resolved = _resolve_authorization(_extract_bearer(authorization))
        except PermissionResolutionError as exc:
            # 503, matching require_permission: "we could not decide" is a different operational
            # problem from "we decided no". Tenancy is no longer carried in the token, so an
            # unreachable host_app means there is nothing to fall back on -- and nothing to fall
            # back TO would be worse: a stale scope honoured after an administrator changed it.
            logger.error('tenant scope resolution via host_app failed: %s', exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail='Authorization temporarily unavailable',
            ) from exc

        tenant_ids = tenant_ids_from(resolved.tenant_ids)
        if not tenant_ids:
            # 403, not 200-with-nothing: a caller with no tenant is misconfigured, and silently
            # returning an empty list would hide that until someone noticed missing data.
            logger.warning(
                'Denying request: host_app reports no usable tenant id (subject=%s)',
                (claims or {}).get('sub'),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='No tenant scope',
            )
        # The fail-closed gate is above this line and the widening below it, in that order and not
        # as an early return: a caller with the cross-tenant permission and no tenant of its own is
        # still denied. The permission widens a scope; it does not conjure one.
        # Resolved through host_app like every other permission. A failure here WIDENS nothing --
        # `read_all` stays False and the caller keeps its own tenants, so an unreachable host_app
        # narrows access rather than granting it.
        read_all = CROSS_TENANT_READ_PERMISSION in resolved.permissions
        if read_all:
            logger.info(
                'Cross-tenant read authorised by %s (subject=%s)',
                CROSS_TENANT_READ_PERMISSION, (claims or {}).get('sub'),
            )
        return TenantScope(tenant_ids=frozenset(tenant_ids), read_all_tenants=read_all)

    return dependency
