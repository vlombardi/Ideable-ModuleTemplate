"""
Test configuration for module_template backend integration tests
Tests run against deployed API, not source code

This file is **framework-owned template infrastructure**: it syncs into every remote module, so the
token-minting below is the one implementation every module inherits. It deliberately does not import
anything from `modules/host_app/` — a remote module project contains only host_app's `module.json`
and `config/`, so any dependency on host_app's own test code would work here and fail there.
"""
import json
import os
from pathlib import Path
import pytest
import requests

# The module's own slug, from the one answer that travels with the module. Env vars are prefixed
# with it uppercased (`TEMPLATE_…` here, `ACMEASSETS_…` in a module called acme_assets), so a
# literal prefix in a force-synced test asserts about a module that does not exist and fails on a
# project that has done nothing wrong. See rules/testing-guidelines.md § Where a test goes.
_MODULE_DIR = Path(__file__).resolve().parents[2]
_SLUG = json.loads((_MODULE_DIR / "module.json").read_text(encoding="utf-8"))["slug"]
_ENV = _SLUG.upper()


_tests_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_tests_dir, "..", "..", "..", ".."))

# Deployed env files, in the order host_app's own suite reads them. A remote module project has
# these too: they are written into deployment_root/ by the deploy, which is the only place a module's
# tests can learn the stack's real ports and secrets without guessing.
try:
    from dotenv import load_dotenv

    for _candidate in (
        os.path.join(_project_root, "project.env.config"),
        os.path.join(_project_root, "project.env.secrets"),
        os.path.join(_project_root, "deployment_root", ".env.config"),
        os.path.join(_project_root, "deployment_root", ".env.secrets"),
        os.path.join(_project_root, "deployment_root", "modules", "host_app", ".env.config"),
        os.path.join(_project_root, "deployment_root", "modules", "host_app", ".env.secrets"),
    ):
        if os.path.exists(_candidate):
            load_dotenv(dotenv_path=_candidate)
except ImportError:  # pragma: no cover - dotenv is a test dependency, absence is a setup problem
    pass


APP_SLUG = os.getenv("APP_SLUG", "ideable")
AUTHENTIK_URL = os.getenv("AUTHENTIK_URL", "http://localhost:9000")
SERVICE_CLIENT_ID = os.getenv("SERVICE_CLIENT_ID") or f"{APP_SLUG}-svc"
SERVICE_CLIENT_SECRET = os.getenv("SERVICE_CLIENT_SECRET", "")

# The module's own slug, and one permission it owns. Asserting on a permission from THIS module —
# rather than a host_app one — is what makes the premise check meaningful: a token that resolves
# host_app permissions but no module permissions would pass a host_app-flavoured check and then 403
# on every endpoint in this suite.
#
# The slug comes from this module's own module.json, NOT from `$MODULE_SLUG`. That variable is
# ambiguous by construction: every module's .env.config defines it, the merged deployment_root file
# carries host_app's value, and the test runner exports it per module — so reading it here resolved
# to "hostapp" and demanded `hostapp.items:view`, a permission that does not exist. module.json is
# the one answer that travels with the module and cannot be shadowed.
def _module_slug():
    import json

    module_json = os.path.join(_tests_dir, "..", "..", "module.json")
    with open(module_json, encoding="utf-8") as fh:
        slug = json.load(fh).get("slug")
    assert slug, f"{module_json} declares no slug — it is the module's identity, and required here"
    return slug


MODULE_SLUG = _module_slug()
REQUIRED_PERMISSION = os.getenv("TEST_REQUIRED_PERMISSION", f"{MODULE_SLUG}.items:view")

# The profile that carries this module's permissions. `admin` holds every module's permissions by
# seed; a module with a bespoke profile can point this elsewhere without editing the fixture.
GRANT_PROFILE = os.getenv("TEST_GRANT_PROFILE", "admin")


@pytest.fixture(scope="session")
def api_base_url():
    """Get API base URL from environment"""
    return os.getenv(f'{_ENV}_API_URL', 'http://localhost:8002/api')


@pytest.fixture(scope="session")
def hostapp_api_url():
    """host_app's API, from the host.

    A remote module's suite needs it since the thin-token change: authorization lives in host_app's tables, so
    provisioning a test persona's profile means going through host_app, not through an Authentik
    attribute.
    """
    return os.getenv("HOSTAPP_API_URL_HOST", "http://localhost:8001/api")


def _mint_service_account_token():
    """Obtain a Bearer token through the confidential service-account provider.

    Same mechanism host_app's suite uses, reimplemented here rather than imported — see the module
    docstring. `client_credentials` is chosen over the e2e personas deliberately: those are gated
    behind `E2E_TEST_USERS_ENABLED` and refused in production, so depending on them would make these
    tests conditional again, which is the exact problem being fixed.
    """
    assert SERVICE_CLIENT_SECRET, (
        "SERVICE_CLIENT_SECRET is not set, so no token can be minted and these tests cannot run.\n"
        "It is written to deployment_root/.env.secrets by the identity bootstrap — check that a "
        "deploy has completed. Alternatively export TEST_AUTH_TOKEN with a token of your own."
    )
    response = requests.post(
        f"{AUTHENTIK_URL}/application/o/token/",
        data={
            "grant_type": "client_credentials",
            "client_id": SERVICE_CLIENT_ID,
            "client_secret": SERVICE_CLIENT_SECRET,
            # The 'hostapp' scope triggers the Ideable claims mapping. Without it the token carries
            # no tenant, and tenant scoping fails CLOSED — every tenant-scoped endpoint denies.
            "scope": "openid profile email hostapp",
        },
        timeout=30,
    )
    assert response.status_code == 200, (
        f"could not mint a service-account token from Authentik: "
        f"{response.status_code} {response.text[:300]}"
    )
    return response.json()["access_token"]


def _grant_profile(headers, hostapp_api):
    """Make the persona hold this module's permissions, and return what it resolves.

    Two steps, in this order for a reason:

    1. `GET /api/me` against host_app auto-provisions the local `users` row and — importantly —
       reports the username the BACKEND resolved. That is not the username Authentik's API reports:
       the token carries a case-normalised `preferred_username`, so granting to Authentik's spelling
       creates a second row and leaves the persona holding nothing.
    2. The profile is granted in SQL. There is no chicken-and-egg way to grant it through an API
       that itself requires a permission to call.

    Step 2 needs host_app's database credentials, which a module's test suite reading
    `deployment_root/` does have. That is a boundary cost worth naming: it is acceptable for test
    infrastructure against a development stack, and it is why this fixture is session-scoped and
    does exactly one write.
    """
    me = requests.get(f"{hostapp_api}/me", headers=headers, timeout=30)
    assert me.status_code == 200, (
        f"GET {hostapp_api}/me with the service-account token: "
        f"{me.status_code} {me.text[:300]}\n"
        f"The token was minted successfully, so this is host_app refusing it — check that the "
        f"backend is up and that the identity plane finished starting (/ready reports "
        f"identity_sync)."
    )
    backend_username = me.json()["username"]

    import psycopg2

    # POSTGRES_HOST in the deployed env is whatever the *containers* use to reach the database —
    # here it resolved to the machine's LAN address (DATABASE_IP). That is not reachable from a test
    # runner on the host, because the database publishes on 127.0.0.1 by default (POSTGRES_BIND).
    # Anything that is not already a loopback name is therefore replaced, matching host_app's own
    # conftest rather than inventing a second rule.
    # …unless the suite is running INSIDE the dev tools container, where the reasoning inverts:
    # `localhost` is the tool container itself and the database is reachable ONLY by its compose
    # service name — exactly the address this rule discards. `run_enabled_tests.sh` exports the
    # service-name host/port, and the image sets IDEABLE_IN_TOOL_CONTAINER=1, so the runner says
    # which case this is rather than the rule guessing.
    _raw_host = (os.getenv("POSTGRES_HOST") or "").strip().lower()
    _in_tool_container = os.getenv("IDEABLE_IN_TOOL_CONTAINER") == "1"
    _is_loopback = _raw_host in {"localhost", "127.0.0.1", "::1"}
    _use_env = _in_tool_container or _is_loopback
    _host = _raw_host if _use_env else "localhost"
    _port = int(os.getenv("POSTGRES_PORT", "5433")) if _use_env else 5433

    conn = psycopg2.connect(
        host=_host,
        port=_port,
        user=os.getenv("POSTGRES_USER", "vinz"),
        password=os.getenv("POSTGRES_PASSWORD", "vinz"),
        dbname=os.getenv("POSTGRES_DB", "vinz"),
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM profiles WHERE name = %s", (GRANT_PROFILE,))
            row = cur.fetchone()
            assert row, (
                f"no {GRANT_PROFILE!r} profile in host_app's database — the authorization seed has "
                f"not run. Check Admin -> System messages for what the seed declined to do."
            )
            profile_id = row[0]

            cur.execute("SELECT id FROM users WHERE username = %s", (backend_username,))
            row = cur.fetchone()
            assert row, (
                f"host_app did not auto-provision {backend_username!r} even though GET /me "
                f"returned 200 — this should be impossible; inspect the users table."
            )
            user_id = row[0]

            cur.execute(
                "INSERT INTO user_profiles (user_fk, profile_fk) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (user_id, profile_id),
            )
            cur.execute(
                "UPDATE users SET active_profile_fk = %s, is_active = TRUE WHERE id = %s",
                (profile_id, user_id),
            )
            # A tenant, granted as explicitly as the profile. Every data endpoint in this module
            # requires tenant scope as well as a permission, and host_app now serves that scope from
            # `users.tenant_fk` on /api/me. The persona used to acquire one indirectly -- the
            # startup sync assigned a default tenant and projected it into an Authentik attribute
            # that the token then carried -- so the fixture never had to say so, and what it
            # actually depended on was invisible. Stating it here also removes the timing: the
            # persona holds its scope on the next call, not after the next sync.
            cur.execute(
                "SELECT id FROM tenants ORDER BY id LIMIT 1"
            )
            tenant_row = cur.fetchone()
            assert tenant_row, (
                "host_app has no tenants at all, so no persona can hold a scope and every "
                "tenant-scoped test would assert 403s for the wrong reason. Seed host_app first."
            )
            cur.execute(
                "UPDATE users SET tenant_fk = %s WHERE id = %s AND tenant_fk IS NULL",
                (tenant_row[0], user_id),
            )
            # Every backend replica must stop serving the pre-grant permission set. Without this
            # bump the grant lands in the database and the running replicas keep denying for up to
            # the cache TTL, which reads as an authorization bug rather than a stale cache.
            cur.execute(
                "INSERT INTO authz_generation (id, value) VALUES (1, 1) "
                "ON CONFLICT (id) DO UPDATE SET value = authz_generation.value + 1"
            )
    finally:
        conn.close()

    me = requests.get(f"{hostapp_api}/me", headers=headers, timeout=30)
    assert me.status_code == 200, f"GET /me after the grant: {me.status_code} {me.text[:300]}"
    return me.json().get("permissions") or []


@pytest.fixture(scope="session")
def auth_token(hostapp_api_url):
    """A Bearer token that actually carries this module's permissions.

    This fixture used to be four lines: read `TEST_AUTH_TOKEN` from the environment and
    `pytest.skip` when it was absent. **Nothing ever set it.** Nineteen tests in this suite —
    authenticated item CRUD, JWT hot-path validation, history pagination — therefore never executed
    in any normal run, while the suite reported them as skips inside a green total. A count of skips
    read as coverage.

    It mints instead, and it FAILS rather than skips when it cannot. These are integration tests
    against a deployed stack: the neighbouring unauthenticated tests in the same files already fail
    outright when the stack is down, so a skip here was never consistent with them — it was only
    quieter.

    `TEST_AUTH_TOKEN` still wins when set, so CI or a developer can inject a specific identity.
    """
    injected = os.getenv("TEST_AUTH_TOKEN")
    if injected:
        return injected

    token = _mint_service_account_token()
    headers = {"Authorization": f"Bearer {token}"}
    granted = _grant_profile(headers, hostapp_api_url)

    assert REQUIRED_PERMISSION in granted, (
        f"the test persona resolves {sorted(granted)!r}, which does not include "
        f"{REQUIRED_PERMISSION!r}.\n"
        f"Every authenticated test in this suite would then be asserting 403s for the wrong reason. "
        f"Check that the {GRANT_PROFILE!r} profile carries this module's permissions — "
        f"`./authz.sh seed --module {MODULE_SLUG}` is what puts them there."
    )
    return token


@pytest.fixture
def auth_headers(auth_token):
    """Get auth headers with bearer token"""
    return {"Authorization": f"Bearer {auth_token}"}
