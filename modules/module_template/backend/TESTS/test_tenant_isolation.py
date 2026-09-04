"""Tenant isolation, exercised end to end with real tokens — and independently at the database.

auth-specs.md §5.5 mandates tenant scoping on every data access. This suite is the acceptance test
for it, and it exists in this shape because of how the previous one failed: it asserted on the
*text* of `crud.py` and `auth.py`, and its one live check accepted either 200 or 403. The isolation
was implemented, the suite was green, and the security property had never been exercised. Worse, the
grep-based assertions would have kept passing while the feature was broken — which it was: the
tenant claim reached the backend as `EU(1)` and the reader parsed only bare integers, so every id
was dropped and every request denied.

So this suite provisions its own reality and then asks the running system questions:

- two Authentik users in different tenants, each with a real token from the real provider;
- a third with no tenant attribute at all, for the fail-closed case;
- a fourth holding `template.items:read_all_tenants`, for the explicit cross-tenant read;
- items created through the API, by the persona that owns them.

Everything it creates it deletes, unconditionally, including when an assertion fails — see
rules/testing-guidelines.md § "A test owns the data it needs". Tenant ids are synthetic and far
above any real one, and every name carries a per-run marker, so the suite is repeatable against a
database that already contains other data, including its own earlier runs.

The database-layer half connects as the application role and asks the questions the API cannot: what
an *unfiltered* query returns. That is the faithful automated form of "comment out the tenant filter
in crud.list_items and check isolation still holds" — a query with no tenant predicate is exactly
what a commented-out filter produces, and it can be run without editing a deployed container.
"""
import json
import os
import re
import uuid
from pathlib import Path

import psycopg2
import pytest
import requests

# The module's own slug, from the one answer that travels with the module. Env vars are prefixed
# with it uppercased (`TEMPLATE_…` here, `ACMEASSETS_…` in a module called acme_assets), so a
# literal prefix in a force-synced test asserts about a module that does not exist and fails on a
# project that has done nothing wrong. See rules/testing-guidelines.md § Where a test goes.
_MODULE_DIR = Path(__file__).resolve().parents[2]
_SLUG = json.loads((_MODULE_DIR / "module.json").read_text(encoding="utf-8"))["slug"]
_ENV = _SLUG.upper()


def _db_endpoint(service: str, published_port) -> tuple[str, int]:
    """Where a database is, from wherever this suite happens to be running.

    On a developer's machine it is the port published on 127.0.0.1. Inside the dev tools container
    that route does not exist — the databases publish on loopback only — so the compose service name
    on its own 5432 is the only way in. Derived from the module slug, so a remote module reaches its
    own database rather than the reference module's.
    """
    if os.getenv("IDEABLE_IN_TOOL_CONTAINER") == "1":
        return service, 5432
    return "127.0.0.1", int(published_port)


_BACKEND = Path(__file__).resolve().parents[1]
_APP = _BACKEND / "SOURCES" / "app"
_REPO_ROOT = _BACKEND.parents[2]

TIMEOUT = 20

# Far above any real tenant, so a mistake in this suite cannot touch a real tenant's rows and a
# leftover row cannot be mistaken for one.
TENANT_A = 900001
TENANT_B = 900002

# ---------------------------------------------------------------------------------------------
# What this module's cross-tenant entity IS — derived, never named
# ---------------------------------------------------------------------------------------------
# This suite is force-synced into every remote module, so a literal `items` / `template_items` in it
# is an assertion about a module that does not exist. It carried three of them and could not pass in
# any module without an `items` entity: observed in a module whose entities are companies, assets
# and assessments as 39 tests, all red, for a reason that had nothing to do with the module. The
# file cannot be adapted (force-synced) or excluded (`pytest.ini` and the root `conftest.py` are
# framework-owned), so a remote had no lever at all.
#
# Tenant isolation is a property EVERY module must prove, not an example — so the fix is to derive,
# from the four sources the module already authors:
#
#   entity, permission, roles  <-  config/authorization.yaml
#   collection route, payload  <-  the running backend's own OpenAPI
#   tables                     <-  app/models.py __tablename__ (as test_migrations.py does)
#
# Each derivation reproduces module_template's former literals exactly, which is the best available
# evidence that it is the right derivation.

_CONFIG = _MODULE_DIR / "config" / "authorization.yaml"
_CROSS_TENANT_SUFFIX = "read_all_tenants"

#: Where the backend mounts its routers, and therefore the prefix its OpenAPI paths carry
#: (`app.include_router(items_router, prefix='/api')`). `api_base_url` already ends in it.
_API_MOUNT = "/api"


def _authorization() -> dict:
    """The module's authorization contract.

    Read with yaml when available and with a deliberately small parser when it is not: this file
    ships to every remote and PyYAML is not guaranteed in a module's test environment, while the
    three shapes needed here (`- role:`/`- profile:` blocks with a `permissions:`/`roles:` list) are
    a fixed subset the framework itself defines.
    """
    text = _CONFIG.read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:  # pragma: no cover — exercised only where PyYAML is absent
        return _parse_authorization_subset(text)
    return yaml.safe_load(text) or {}


def _parse_authorization_subset(text: str) -> dict:
    """`profiles`/`roles` with their `roles`/`permissions` lists. Nothing else is needed here."""
    out: dict[str, list] = {"profiles": [], "roles": []}
    section = None
    entry = None
    listkey = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if re.match(r"^(profiles|roles|permissions):", line):
            section = line.split(":", 1)[0]
            entry = None
            listkey = None
            continue
        if section not in ("profiles", "roles"):
            continue
        m = re.match(r"^\s{2}-\s+(ext_profile|profile|ext_role|role):\s*(\S+)", line)
        if m:
            entry = {m.group(1): m.group(2)}
            out[section].append(entry)
            listkey = None
            continue
        if entry is None:
            continue
        m = re.match(r"^\s{4}(roles|permissions):", line)
        if m:
            listkey = m.group(1)
            entry[listkey] = []
            continue
        m = re.match(r"^\s{6}-\s+(\S+)", line)
        if m and listkey:
            entry[listkey].append(m.group(1))
    return out


def _role_names(entry: dict) -> str | None:
    return entry.get("role") or entry.get("ext_role")


def _profile_names(entry: dict) -> str | None:
    return entry.get("profile") or entry.get("ext_profile")


class _ContractUnresolved(Exception):
    """The three names this suite needs do not agree, or one of them is missing.

    Raised — and caught at module scope — rather than asserted, because **where** this failure
    surfaces decides whether anyone can read it. These derivations run while the module is being
    imported. A bare `assert` there is a *collection error*: pytest reports that the file could not
    be imported and every test in it goes red at once, so the one sentence naming which of the three
    names disagrees is buried under 36 failures that say nothing.

    A contract suite that cannot report its own precondition failure reports nothing. So the problem
    is captured, one dedicated test states it, and the rest of the suite skips with the reason.
    """


def _cross_tenant_target() -> tuple[str, str, str, str]:
    """(entity, qualified permission, the profile that may read across tenants, the module's own
    editing profile).

    The entity is whichever one this module declares cross-tenant readable: exactly the permission
    `<entity>:read_all_tenants` in `config/authorization.yaml`. That is a better source than the
    OpenAPI, because it is the module's own statement of which entity the property applies to
    rather than a guess from the shape of a route.

    The permission is stored unprefixed and the module slug is added at bootstrap, which is why the
    token carries `<slug>.<entity>:read_all_tenants`.
    """
    doc = _authorization()
    roles = doc.get("roles") or []
    profiles = doc.get("profiles") or []

    entity = None
    cross_role = None
    for role in roles:
        for permission in role.get("permissions") or []:
            m = re.fullmatch(rf"([\w-]+):{_CROSS_TENANT_SUFFIX}", str(permission))
            if m:
                entity, cross_role = m.group(1), _role_names(role)
                break
        if entity:
            break
    if not (entity and cross_role):
        raise _ContractUnresolved(
            f"{_CONFIG} declares no `<entity>:{_CROSS_TENANT_SUFFIX}` permission. Every module must "
            f"name the entity it allows a cross-tenant read of, and the role that may do it — see "
            f"auth-specs.md §5.5. Without it this suite cannot know what to prove."
        )

    # The role that can WRITE the entity: the persona that owns a tenant's rows needs it to create
    # the fixtures the isolation assertions are about.
    edit_role = None
    for role in roles:
        if f"{entity}:edit" in (role.get("permissions") or []):
            edit_role = _role_names(role)
            break
    if not edit_role:
        raise _ContractUnresolved(
            f"{_CONFIG} declares no role holding `{entity}:edit`, so no persona can create the rows "
            f"this suite needs to prove one tenant cannot see another's"
        )

    def _profile_holding(role_name: str, prefer_own: bool) -> str | None:
        """The profile that grants `role_name`.

        `prefer_own` picks the module's OWN profile (`profile:`) over host_app's (`ext_profile:`)
        when both grant the role — the editing persona must administer one tenant, not the
        installation. The cross-tenant reader is the mirror image: the framework grants that role to
        host_app's application-wide profile precisely so that "administrator" does not imply "sees
        everything", so there its `ext_profile` is the right and only answer.
        """
        own = [p for p in profiles if role_name in (p.get("roles") or []) and p.get("profile")]
        ext = [p for p in profiles if role_name in (p.get("roles") or []) and p.get("ext_profile")]
        order = (own + ext) if prefer_own else (ext + own)
        return _profile_names(order[0]) if order else None

    cross_profile = _profile_holding(cross_role, prefer_own=False)
    edit_profile = _profile_holding(edit_role, prefer_own=True)
    if not cross_profile:
        raise _ContractUnresolved(f"no profile in {_CONFIG} grants {cross_role!r}")
    if not edit_profile:
        raise _ContractUnresolved(f"no profile in {_CONFIG} grants {edit_role!r}")
    return entity, f"{_SLUG}.{entity}:{_CROSS_TENANT_SUFFIX}", cross_profile, edit_profile


#: What a module may DECLARE, when its three names cannot be one token.
#:
#: The default is the identity convention: the entity named by `<entity>:read_all_tenants` is also
#: the collection route segment and the table's unprefixed name — `items` / `/items` /
#: `template_items`, which is what this module uses and what most modules will.
#:
#: It is a default and not a requirement, because requiring a public REST collection path to equal
#: a database table name is a coupling the framework has no business imposing. Kebab-plural routes
#: over snake-singular tables is ordinary, defensible REST, and a module that has it satisfies
#: neither derivation: of one reported module's 23 `POST` collections, four were single-token paths
#: the derivation could consider and none matched a table. Renaming a table to satisfy a test suite
#: is the tail wagging the dog, so the mapping is statable instead:
#:
#:     "crossTenantEntity": { "collectionRoute": "/assessments", "table": "sra_assessments" }
#:
#: Either key may be omitted; the convention fills in whatever is not declared.
_CROSS_TENANT_ENTITY_FIELD = "crossTenantEntity"


def _declared_entity_mapping() -> dict:
    meta = json.loads((_MODULE_DIR / "module.json").read_text(encoding="utf-8"))
    declared = meta.get(_CROSS_TENANT_ENTITY_FIELD) or {}
    return declared if isinstance(declared, dict) else {}


def _entity_tables(entity: str) -> tuple[str, str]:
    """(the entity's table, its Continuum version table).

    Declared in `module.json` when the module says so; otherwise from the one authored definition —
    `app/models.py`, the schema's source of truth, matched to the entity by suffix because a module
    prefixes its tables with its own db prefix (`template_items`, `sra_companies`).
    """
    declared = str(_declared_entity_mapping().get("table") or "").strip()
    models = _APP / "models.py"
    tables = re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]", models.read_text(encoding="utf-8"))
    if not tables:
        raise _ContractUnresolved(f"{models} declares no __tablename__ — the extraction has drifted")

    if declared:
        if declared not in tables:
            raise _ContractUnresolved(
                f"module.json declares {_CROSS_TENANT_ENTITY_FIELD}.table = {declared!r}, and "
                f"{models} declares no such __tablename__. Declared: {sorted(tables)}."
            )
        return declared, f"{declared}_version"

    matches = [t for t in tables if t == entity or t.endswith(f"_{entity}")]
    if not matches:
        raise _ContractUnresolved(
            f"no table in {models} matches the entity {entity!r} named by "
            f"`{entity}:{_CROSS_TENANT_SUFFIX}` in {_CONFIG}.\n"
            f"  permission entity : {entity}\n"
            f"  tables declared   : {sorted(tables)}\n"
            f"By default the three names are one token — the permission entity, the collection "
            f"route segment and the table's unprefixed name. When they cannot be, declare the "
            f"mapping instead of renaming: add to modules/<MODULE>/module.json\n"
            f'    "{_CROSS_TENANT_ENTITY_FIELD}": {{"collectionRoute": "/<route>", '
            f'"table": "<table>"}}\n'
            f"See auth-specs.md §5.5."
        )
    table = matches[0]
    return table, f"{table}_version"


def _resolve_contract():
    """Resolve every name this suite needs, or record why it could not.

    Returns `(values, problem)` where exactly one is set. Nothing raises out of module scope: that
    is the whole point — see `_ContractUnresolved`.
    """
    try:
        entity, permission, cross_profile, admin_profile = _cross_tenant_target()
        table, version_table = _entity_tables(entity)
    except _ContractUnresolved as exc:
        return None, str(exc)
    except (OSError, ValueError) as exc:
        return None, f"the tenancy contract could not be read: {exc}"
    return (entity, permission, cross_profile, admin_profile, table, version_table), None


_CONTRACT, CONTRACT_PROBLEM = _resolve_contract()

#: Placeholders when the contract is unresolved. Every test that would use them is skipped by
#: `_the_contract_must_resolve` below, so they are never dereferenced against a real system — they
#: exist so that *importing* the module succeeds and pytest can report one failure instead of 36.
_UNRESOLVED = "<tenancy-contract-unresolved>"
(
    _ENTITY,
    CROSS_TENANT_PERMISSION,
    CROSS_TENANT_PROFILE,
    ENTITY_ADMIN_PROFILE,
    ENTITY_TABLE,
    ENTITY_VERSION_TABLE,
) = _CONTRACT or (_UNRESOLVED,) * 6


#: The precondition is ASSERTED in `test_tenancy_contract_names.py`, not here, and deliberately so.
#:
#: Every test in this file is gated on a live stack — `purge_synthetic_audit_residue` is
#: session-scoped and autouse and depends on `stack`, so a checkout with nothing running skips the
#: whole file. A naming disagreement is a static fact about three files, and putting its assertion
#: here would mean the one report a module needs is available only in the situation where it is
#: least urgent. The companion file is stack-free, so a remote learns it from the earliest run it
#: can make.


@pytest.fixture(scope="session")
def _the_contract_resolved_or_no_session():
    """The SESSION-scoped half of the guard, and it is load-bearing.

    A function-scoped skip is not enough on its own. Session fixtures are set up before any
    function-scoped fixture gets a chance to skip, and their teardown runs regardless — so
    `purge_synthetic_audit_residue` would build `DELETE FROM <tenancy-contract-unresolved>` and the
    run would end in a teardown ERROR rather than the clean skips this arrangement is for. Skipping
    here refuses the session fixture itself, so nothing is ever set up against a placeholder.
    """
    if CONTRACT_PROBLEM:
        pytest.skip(f"tenancy contract unresolved: {CONTRACT_PROBLEM}")


@pytest.fixture(autouse=True)
def _the_contract_must_resolve():
    """Skip this suite when the contract did not resolve, naming why.

    A skip, not a failure: these tests assert tenant isolation and can say nothing about it when
    they do not know which entity to exercise. Reporting 39 isolation failures for a naming
    disagreement is the over-stated signal this whole change is about — one true failure (in the
    companion file) and honest skips here is the same information, readable.

    Kept alongside the session-scoped guard above rather than replaced by it: this one gives every
    test the reason in its own skip message, which is what a reader of the report sees.
    """
    if CONTRACT_PROBLEM:
        pytest.skip(f"tenancy contract unresolved: {CONTRACT_PROBLEM}")


# ---------------------------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------------------------
_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _load_env() -> dict:
    """Settings from the deployed env files, falling back to the process environment.

    The runner does not source these, and the suite needs three things no default can supply: the
    Authentik admin token, the confidential service-account client secret, and the application
    role's database password.

    References are expanded, because these files are full of them — `AUTHENTIK_PORT_HTTP` is
    literally `${HOSTAPP_AUTHENTIK_HTTP_PORT:-9000}` and `SERVICE_CLIENT_SECRET` is
    `${HOSTAPP_SERVICE_CLIENT_SECRET}`. A parser that returns the reference text builds a URL
    containing `${...}` and a secret that is not one, and the suite then looks like a stack that is
    not running.
    """
    values: dict[str, str] = {}
    for name in (
        "project.env.config", "project.env.secrets",
        "deployment_root/.env.config", "deployment_root/.env.secrets",
    ):
        path = _REPO_ROOT / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")

    # Iterated, because a reference may point at another reference. Bounded, so a circular one
    # leaves the text in place instead of hanging.
    def _expand(text: str) -> str:
        return _VAR_REF.sub(
            lambda m: values.get(m.group(1)) or (m.group(2) if m.group(2) is not None else m.group(0)),
            text,
        )

    for _ in range(5):
        expanded = {k: _expand(v) for k, v in values.items()}
        if expanded == values:
            break
        values = expanded

    # The process environment fills GAPS only. An explicit export should not silently shadow the
    # env files that describe the stack actually running.
    for key, value in os.environ.items():
        values.setdefault(key, value)
    return values


@pytest.fixture(scope="session")
def env():
    return _load_env()


# Environment first: inside the dev tools container `localhost` is the container, not the host, and
# the `stack` fixture below turns an unreachable stack into a SKIP rather than a failure — so looking
# in the wrong place does not fail loudly, it silently stops testing. (Framework-owned and synced to
# every remote, so the same reasoning has to hold there.)
@pytest.fixture(scope="session")
def authentik_url(env):
    return os.getenv("AUTHENTIK_URL") or f"http://localhost:{env.get('AUTHENTIK_PORT_HTTP', '9000')}"


@pytest.fixture(scope="session")
def stack(env, authentik_url, api_base_url):
    """Refuse to run without a live stack — and refuse to *skip* for anything else.

    A skip here is only ever about a deliberately absent environment: no stack running. Anything
    else (a missing secret, an unreachable provider, a rejected token) is a failure, because a suite
    that skips when it cannot provision is a suite that never runs again.
    """
    try:
        requests.get(f"{authentik_url}/-/health/live/", timeout=5).raise_for_status()
        requests.get(f"{api_base_url.rsplit('/api', 1)[0]}/health", timeout=5)
    except Exception as exc:  # noqa: BLE001 — no stack is the one legitimate skip
        pytest.skip(f"no running stack to test isolation against ({type(exc).__name__}: {exc})")

    missing = [
        key for key in ("AUTHENTIK_BOOTSTRAP_TOKEN", "SERVICE_CLIENT_SECRET",
                        f"{_ENV}_APP_DB_PASSWORD", f"{_ENV}_APP_DB_USER",
                        f"{_ENV}_ENTITIES_DB_NAME", f"{_ENV}_POSTGRES_PORT",
                        # Authorization lives in host_app's database, so the suite
                        # needs to reach it to provision its own personas' profiles.
                        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        if not env.get(key)
    ]
    assert not missing, (
        f"the stack is up but {missing} are not resolvable from project.env.* / "
        f"deployment_root/.env.* — the suite cannot provision its own identities without them"
    )
    return env


class Authentik:
    """The slice of Authentik's admin API this suite needs, plus token issuance."""

    def __init__(self, base_url: str, token: str, client_id: str, client_secret: str):
        self.base_url = base_url
        self._token = token
        self._client_id = client_id
        self._client_secret = client_secret

    def api(self, path: str, method: str = "GET", payload: dict | None = None):
        response = requests.request(
            method, f"{self.base_url}/api/v3/{path}",
            json=payload, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {self._token}"},
        )
        assert response.status_code < 400, (
            f"Authentik {method} {path} failed: {response.status_code} {response.text[:300]}"
        )
        return response.json() if response.content else {}

    def group_pk(self, name: str) -> str:
        """The group's pk, CREATING it if Authentik does not have it.

        This used to assert the group already existed, with the message "the authorization bootstrap
        has not run". That message stopped being true at the thin-token change, which moved authorization out of
        Authentik into host_app's tables: `template_admin` is a **profile** and a **bootstrap user**
        now (`config/authorization.yaml`, `config/bootstrap-users.yaml`), and nothing creates an
        Authentik *group* by that name any more.

        The tests kept passing only because a pre-16b-1 identity volume still carried the legacy
        group. When that volume was recreated fresh, 31 tests began erroring — on `main` as well as
        on any branch, so this was never anything a change had broken.

        A group here is just the vehicle for putting a service account somewhere; the suite does not
        care who else is in it. So it owns the data it needs, per `rules/testing-guidelines.md`
        § "A test owns the data it needs (mandatory)", rather than depending on residue from an
        older deployment.
        """
        results = self.api(f"core/groups/?name={name}").get("results", [])
        if results:
            return results[0]["pk"]
        created = self.api("core/groups/", "POST", {"name": name})
        assert created.get("pk"), f"could not create Authentik group {name!r}: {created}"
        return created["pk"]

    def create_service_account(self, username: str, attributes: dict, group: str | None) -> dict:
        """A service account, because it is the only identity a test can log in AS.

        Authentik's `client_credentials` grant accepts a service account's username plus an app
        password and issues a token carrying *that user's* attributes — which is what makes two
        tokens with two different tenant claims possible at all. A browser flow cannot be automated
        here, and a shared service token would carry one identity for every persona.
        """
        user = self.api("core/users/", "POST", {
            "username": username, "name": username,
            "type": "service_account", "attributes": attributes,
        })
        if group:
            self.api(f"core/groups/{self.group_pk(group)}/add_user/", "POST", {"pk": user["pk"]})
        token = self.api("core/tokens/", "POST", {
            "identifier": f"{username}-app-password", "intent": "app_password",
            "user": user["pk"], "description": "tenant isolation suite", "expiring": False,
        })
        user["_token_identifier"] = token["identifier"]
        user["_app_password"] = self.api(
            f"core/tokens/{token['identifier']}/view_key/"
        )["key"]
        return user

    def delete_service_account(self, user: dict) -> None:
        for path in (f"core/tokens/{user['_token_identifier']}/", f"core/users/{user['pk']}/"):
            try:
                requests.delete(f"{self.base_url}/api/v3/{path}", timeout=TIMEOUT,
                                headers={"Authorization": f"Bearer {self._token}"})
            except Exception:  # noqa: BLE001,S110 — best-effort teardown; raising here would mask the real test failure
                pass

    def access_token(self, username: str, app_password: str) -> str:
        response = requests.post(
            f"{self.base_url}/application/o/token/", timeout=TIMEOUT,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id, "client_secret": self._client_secret,
                "username": username, "password": app_password,
                # Without the `hostapp` scope the property mapping never runs, so the token carries
                # neither permissions nor tenants and every endpoint answers 403 for the wrong
                # reason.
                "scope": "openid profile email hostapp",
            },
        )
        assert response.status_code == 200, (
            f"Authentik refused a token for {username}: "
            f"{response.status_code} {response.text[:300]}"
        )
        return response.json()["access_token"]


@pytest.fixture(scope="session")
def authentik(stack, authentik_url):
    app_slug = stack.get("APP_SLUG", "ideable")
    return Authentik(
        authentik_url,
        stack["AUTHENTIK_BOOTSTRAP_TOKEN"],
        stack.get("SERVICE_CLIENT_ID") or f"{app_slug}-svc",
        stack["SERVICE_CLIENT_SECRET"],
    )


# ---------------------------------------------------------------------------------------------
# The entity's HTTP surface — read from the running backend's own OpenAPI
# ---------------------------------------------------------------------------------------------
# The route and the create payload are the two things `config/authorization.yaml` and `models.py`
# cannot supply: an entity's collection path and its required fields are the API's own statement.
# Discovered the same way `frontend/TESTS/playwright/tests/crud-endpoints.spec.ts` already does it
# for the generic CRUD suite — a `POST /X` with a matching `/X/{id}` carrying `delete` — so the two
# force-synced suites agree on what a CRUD resource is.
class EntityApi:
    """Where this module's cross-tenant entity lives, and what it takes to create one."""

    def __init__(self, spec: dict, collection: str, list_key: str = ""):
        self._spec = spec
        #: The path as the OpenAPI document spells it, INCLUDING the `/api` mount prefix
        #: (`/api/items`). Used only to look schemas up in `spec["paths"]`.
        self.spec_collection = collection
        #: The same path RELATIVE to the api mount (`/items`), which is what a request appends to
        #: `api_base_url` — and `api_base_url` already ends in `/api`.
        #:
        #: Keeping one field for both is what broke this suite the first time it ran against a live
        #: stack: the discovered `/api/items` was appended to `…/api`, every request went to
        #: `/api/api/items`, and 29 tests failed on a 404 that had nothing to do with tenancy. The
        #: two paths are different strings for different jobs, so they are two fields.
        self.collection = collection[len(_API_MOUNT):] if collection.startswith(_API_MOUNT) else collection
        self.list_key = list_key

    def _resolve(self, schema: dict | None) -> dict:
        if schema and "$ref" in schema:
            node: object = self._spec
            for part in str(schema["$ref"]).lstrip("#/").split("/"):
                node = (node or {}).get(part) if isinstance(node, dict) else None
            return node if isinstance(node, dict) else {}
        return schema or {}

    def _sample(self, schema: dict, marker: str):
        s = self._resolve(schema)
        if s.get("enum"):
            return s["enum"][0]
        for key in ("anyOf", "oneOf"):
            if s.get(key):
                # A nullable field is `anyOf: [T, null]`; the first non-null branch is the value.
                for branch in s[key]:
                    resolved = self._resolve(branch)
                    if resolved.get("type") != "null":
                        return self._sample(resolved, marker)
        kind = s.get("type")
        if kind in ("integer", "number"):
            return 1
        if kind == "boolean":
            return False
        if kind == "array":
            return []
        if kind == "object":
            return {}
        return marker

    def _body(self, verb: str, marker: str, path: str | None = None) -> dict:
        target = path or self.spec_collection
        schema = (
            self._spec["paths"][target][verb]
            .get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        resolved = self._resolve(schema)
        required = resolved.get("required") or []
        body = {}
        for name, prop in (resolved.get("properties") or {}).items():
            if name in required:
                value = self._sample(prop, marker)
                body[name] = f"{marker}-{name}" if isinstance(value, str) else value
        return body

    def create_body(self, marker: str) -> dict:
        """The minimum this module's API accepts to create one row of the entity.

        Only `required` properties are sent. A field the schema does not require is one the module
        chose to default, and inventing a value for it would make this suite assert about a payload
        no client sends.
        """
        return self._body("post", marker)

    def update_body(self, marker: str) -> dict:
        return self._body("put", marker, path=self._spec_item_path)


@pytest.fixture(scope="session")
def entity_api(stack, api_base_url) -> EntityApi:
    """This module's cross-tenant entity, as its own API describes it.

    Fails rather than skips when the entity named by `<entity>:read_all_tenants` has no CRUD
    resource: the authorization contract promised a cross-tenant-readable entity and the API does
    not serve one, which is a real disagreement and not an absent environment.
    """
    response = requests.get(f"{api_base_url}/openapi.json", timeout=TIMEOUT)
    assert response.status_code == 200, (
        f"the backend served no OpenAPI at {api_base_url}/openapi.json: "
        f"{response.status_code} {response.text[:200]}"
    )
    spec = response.json()
    paths = spec.get("paths") or {}

    # The collection route. Declared in module.json when the module says so; otherwise the entity
    # named by the permission IS the path segment, which is the convention and this module's case.
    declared_route = str(_declared_entity_mapping().get("collectionRoute") or "").strip()
    wanted = declared_route.strip("/") if declared_route else _ENTITY
    candidates = [
        path for path in paths
        if re.fullmatch(rf"(/api)?/{re.escape(wanted)}", path) and "post" in paths[path]
    ]
    assert candidates, (
        f"no `POST /{wanted}` in the backend's OpenAPI.\n"
        f"  permission entity : {_ENTITY}   (from `{_ENTITY}:{_CROSS_TENANT_SUFFIX}` in {_CONFIG})\n"
        f"  collection route  : /{wanted}"
        + (f"   (declared in module.json {_CROSS_TENANT_ENTITY_FIELD}.collectionRoute)\n"
           if declared_route else "   (by the default convention: same token as the entity)\n")
        + f"  table             : {ENTITY_TABLE}\n"
        f"Either the permission names an entity the API does not serve, or this module's route "
        f"does not use the entity's own token — in which case declare the mapping rather than "
        f"renaming the route: add to modules/<MODULE>/module.json\n"
        f'    "{_CROSS_TENANT_ENTITY_FIELD}": {{"collectionRoute": "/<route>", '
        f'"table": "{ENTITY_TABLE}"}}\n'
        f"See auth-specs.md §5.5. Collections this API does serve with a POST: "
        f"{sorted(p for p in paths if 'post' in paths[p])[:12]}"
    )
    collection = candidates[0]

    item_paths = [
        path for path in paths
        if re.fullmatch(rf"{re.escape(collection)}/\{{[^}}]+\}}", path) and "delete" in paths[path]
    ]
    assert item_paths, f"{collection} has no `/{{id}}` path with a delete — not a CRUD resource"

    # The list envelope's array property, from the GET's own 200 schema. It is the framework's
    # pagination shape (`items`/`total`/`page`) and NOT the entity name — deriving it from the
    # schema is what keeps that true for a module whose entity is called something else.
    api = EntityApi(spec, collection, list_key="")
    get_schema = api._resolve(
        (paths[api.spec_collection].get("get", {}).get("responses", {}).get("200", {})
         .get("content", {}).get("application/json", {}).get("schema"))
    )
    arrays = [
        name for name, prop in (get_schema.get("properties") or {}).items()
        if api._resolve(prop).get("type") == "array"
    ]
    assert len(arrays) == 1, (
        f"GET {collection} returns {len(arrays)} array properties {arrays}; this suite needs "
        f"exactly one to know where the rows are"
    )
    api.list_key = arrays[0]
    api._spec_item_path = item_paths[0]
    return api


@pytest.fixture(scope="session")
def marker():
    """One marker per run, in every name this suite creates.

    A suite that reuses fixed names passes once and then collides with its own residue.
    """
    return f"e2e-tenant-{uuid.uuid4().hex[:8]}"


class Persona:
    """A provisioned identity plus the calls this suite makes as it."""

    def __init__(self, session: requests.Session, api_base_url: str, tenant_id: int | None):
        self.session = session
        self.api_base_url = api_base_url
        self.tenant_id = tenant_id

    def get(self, path, **kwargs):
        return self.session.get(f"{self.api_base_url}{path}", timeout=TIMEOUT, **kwargs)

    def post(self, path, **kwargs):
        return self.session.post(f"{self.api_base_url}{path}", timeout=TIMEOUT, **kwargs)

    def put(self, path, **kwargs):
        return self.session.put(f"{self.api_base_url}{path}", timeout=TIMEOUT, **kwargs)

    def delete(self, path, **kwargs):
        return self.session.delete(f"{self.api_base_url}{path}", timeout=TIMEOUT, **kwargs)

    def create_row(self, api, marker: str, **overrides) -> dict:
        body = {**api.create_body(marker), **overrides}
        response = self.post(api.collection, json=body)
        assert response.status_code == 201, (
            f"could not create the {_ENTITY} row this test needs via "
            f"POST {api.collection} {body}: {response.status_code} {response.text[:300]}"
        )
        return response.json()

    def row_ids(self, api, **params) -> set[int]:
        response = self.get(api.collection, params={"limit": 200, **params})
        assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
        return {row["id"] for row in response.json()[api.list_key]}


def _persona(authentik, api_base_url, stack, hostapp_api_url, username, tenant_id, group,
             profile, extra_attrs=None):
    """Provision one identity, yield it, and remove it whatever happens."""
    # No tenant attribute is set in Authentik: tenancy is host_app data, served on /api/me, and
    # writing it here would provision the persona through a path the product no longer has.
    attributes = dict(extra_attrs or {})
    user = authentik.create_service_account(username, attributes, group)
    try:
        token = authentik.access_token(username, user["_app_password"])
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {token}"})

        # The profile is granted in host_app's database, not as an Authentik attribute.
        # Setting `hostapp.active_profile` used to be how a persona got its permissions; it now
        # grants nothing, and a persona built that way holds a valid token and no authorization at
        # all -- which reads as an isolation failure rather than as a fixture that stopped working.
        if profile:
            _grant_profile_in_hostapp(stack, hostapp_api_url, session, username, profile, tenant_id)

        persona = Persona(session, api_base_url, tenant_id)
        persona.username = username
        persona.token = token
        yield persona
    finally:
        authentik.delete_service_account(user)


def _grant_profile_in_hostapp(stack, hostapp_api_url, session, username, profile, tenant_id=None):
    """Auto-provision the persona in host_app, then grant it `profile` and its tenant there.

    Both halves of a persona's authorization are now host_app rows. Tenancy used to be an Authentik
    user attribute rendered into a `hostapp.tenant_ids` claim; a fixture written that way now
    produces a persona holding a valid token and no tenant scope at all, which reads as an isolation
    failure rather than as a fixture that stopped working.
    """
    # host_app auto-provisions a users row on first authenticated call, and reports the username it
    # resolved — which is not always Authentik's spelling (the token carries a case-normalised
    # preferred_username). Granting to the wrong one creates a second row and grants nothing.
    me = session.get(f"{hostapp_api_url}/me", timeout=20)
    assert me.status_code == 200, f"GET /me: {me.status_code} {me.text[:300]}"
    username = me.json()["username"]

    _h, _p = _db_endpoint("database", stack.get("HOSTAPP_POSTGRES_PORT") or stack.get("POSTGRES_PORT", "5433"))
    connection = psycopg2.connect(
        host=_h, port=_p,
        user=stack["POSTGRES_USER"], password=stack["POSTGRES_PASSWORD"],
        dbname=stack["POSTGRES_DB"],
    )
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM profiles WHERE name = %s", (profile,))
            row = cursor.fetchone()
            assert row, f"no {profile!r} profile in host_app — the authorization seed has not run"
            profile_id = row[0]

            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            row = cursor.fetchone()
            assert row, (
                f"host_app did not auto-provision {username!r} — check that GET /me accepted the "
                f"persona's token"
            )
            user_id = row[0]

            cursor.execute(
                "INSERT INTO user_profiles (user_fk, profile_fk) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING", (user_id, profile_id),
            )
            cursor.execute(
                "UPDATE users SET active_profile_fk = %s WHERE id = %s", (profile_id, user_id),
            )
            if tenant_id is not None:
                # The tenant must be a real host_app row, because /api/me renders its tag from one.
                # `E2E<id>` keeps the tag identical to what this suite asserted when it came from a
                # claim -- `TenantName(ID)` -- so the reader is still exercised against the format
                # the system actually emits, which is what caught the parsing bug.
                cursor.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (tenant_id, f"E2E{tenant_id}"),
                )
                cursor.execute(
                    "UPDATE users SET tenant_fk = %s WHERE id = %s", (tenant_id, user_id),
                )

            cursor.execute(
                "INSERT INTO authz_generation (id, value) VALUES (1, 1) "
                "ON CONFLICT (id) DO UPDATE SET value = authz_generation.value + 1"
            )
    finally:
        connection.close()


@pytest.fixture(scope="class")
def tenant_a(authentik, api_base_url, stack, hostapp_api_url, marker):
    yield from _persona(authentik, api_base_url, stack, hostapp_api_url, f"{marker}-a", TENANT_A,
                        ENTITY_ADMIN_PROFILE, ENTITY_ADMIN_PROFILE)


@pytest.fixture(scope="class")
def tenant_b(authentik, api_base_url, stack, hostapp_api_url, marker):
    yield from _persona(authentik, api_base_url, stack, hostapp_api_url, f"{marker}-b", TENANT_B,
                        ENTITY_ADMIN_PROFILE, ENTITY_ADMIN_PROFILE)


@pytest.fixture(scope="class")
def no_tenant(authentik, api_base_url, stack, hostapp_api_url, marker):
    """Permissions but no tenant attribute: the misconfiguration that must deny, not widen."""
    yield from _persona(authentik, api_base_url, stack, hostapp_api_url, f"{marker}-nt", None,
                        ENTITY_ADMIN_PROFILE, ENTITY_ADMIN_PROFILE)


@pytest.fixture(scope="class")
def cross_reader(authentik, api_base_url, stack, hostapp_api_url, marker):
    """Own tenant A *plus* the named cross-tenant read permission.

    The profile is the one `config/authorization.yaml` grants the cross-tenant role to — by
    framework convention host_app's application-wide profile, never the module's own admin, so
    that "administers this module" does not imply "sees every tenant".
    """
    yield from _persona(authentik, api_base_url, stack, hostapp_api_url, f"{marker}-x", TENANT_A,
                        CROSS_TENANT_PROFILE, CROSS_TENANT_PROFILE)


@pytest.fixture(scope="class")
def item_a(tenant_a, entity_api, marker):
    row = tenant_a.create_row(entity_api, f"{marker}-A")
    yield row
    tenant_a.delete(f"{entity_api.collection}/{row['id']}")


@pytest.fixture(scope="class")
def item_b(tenant_b, entity_api, marker):
    row = tenant_b.create_row(entity_api, f"{marker}-B")
    yield row
    tenant_b.delete(f"{entity_api.collection}/{row['id']}")


# ---------------------------------------------------------------------------------------------
# Database, as the application role
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="class")
def app_role_db(stack):
    """A connection as the APPLICATION role, not the owner.

    The distinction is the entire reason the database layer works: the owner is a superuser, and
    superusers bypass RLS unconditionally — with the policies enabled *and* forced, a session set to
    tenant 1 still returned tenant 2's rows. Connecting as the owner here would test nothing.
    """
    _h, _p = _db_endpoint(f"{_SLUG}-database", stack[f"{_ENV}_POSTGRES_PORT"])
    connection = psycopg2.connect(
        host=_h, port=_p,
        user=stack[f"{_ENV}_APP_DB_USER"], password=stack[f"{_ENV}_APP_DB_PASSWORD"],
        dbname=stack[f"{_ENV}_ENTITIES_DB_NAME"],
    )
    yield connection
    connection.close()


@pytest.fixture(scope="session", autouse=True)
def purge_synthetic_audit_residue(stack, _the_contract_resolved_or_no_session):
    """Delete the audit rows the suite's items leave behind, once, at the very end.

    Deleting an item through the API removes the row but not its history — the audit trail is
    append-only, correctly. That still leaves residue this suite owns, and it would grow by ~30 rows
    per run forever, so the suite removes its own.

    Scoped to the synthetic tenant ids and nothing else, and run as the OWNER because the
    application role has no business deleting audit rows. `transaction` / `transaction_meta` rows are
    deliberately left: one transaction can cover several entities, so matching them by anything other
    than a tenant would risk a real one's history for the sake of a handful of orphan rows.
    """
    yield
    _h, _p = _db_endpoint(f"{_SLUG}-database", stack[f"{_ENV}_POSTGRES_PORT"])
    connection = psycopg2.connect(
        host=_h, port=_p,
        user=stack[f"{_ENV}_ENTITIES_DB_USER"], password=stack[f"{_ENV}_ENTITIES_DB_PASSWORD"],
        dbname=stack[f"{_ENV}_ENTITIES_DB_NAME"],
    )
    try:
        with connection, connection.cursor() as cursor:
            # The owner is subject to FORCE ROW LEVEL SECURITY too, so it must say who it is.
            cursor.execute("SELECT set_config('app.tenant_ids', %s, true)",
                           (f"{TENANT_A},{TENANT_B}",))
            cursor.execute(
                f"DELETE FROM {ENTITY_VERSION_TABLE} WHERE tenant_id = ANY(%s)",
                ([TENANT_A, TENANT_B],),
            )
            cursor.execute(
                f"DELETE FROM {ENTITY_TABLE} WHERE tenant_id = ANY(%s)",
                ([TENANT_A, TENANT_B],),
            )
    finally:
        connection.close()


def _as_tenants(connection, tenant_ids, statement, params=(), cross_read=False):
    """Run one statement in a transaction scoped to `tenant_ids`. Returns (rows, rowcount)."""
    connection.rollback()
    with connection.cursor() as cursor:
        if tenant_ids is not None:
            cursor.execute("SELECT set_config('app.tenant_ids', %s, true)",
                           (",".join(str(t) for t in tenant_ids),))
        cursor.execute("SELECT set_config('app.cross_tenant_read', %s, true)",
                       ("on" if cross_read else "off",))
        cursor.execute(statement, params)
        rows = cursor.fetchall() if cursor.description else []
        count = cursor.rowcount
    connection.rollback()
    return rows, count


# ---------------------------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------------------------
class TestFailClosed:
    """A missing tenant claim must deny. Never fall back to "all tenants"."""

    def test_the_token_really_carries_no_tenant(self, no_tenant, hostapp_api_url):
        """Otherwise this class would be asserting 403 for some other reason."""
        import base64
        import json
        payload = no_tenant.token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        assert not claims.get("hostapp.tenant_ids"), claims.get("hostapp.tenant_ids")
        # The permission half of the premise now comes from host_app, because the token carries no
        # permissions at all. Without this the 403s below could be denials for the
        # wrong reason.
        me = requests.get(
            f"{hostapp_api_url}/me", headers={"Authorization": f"Bearer {no_tenant.token}"},
            timeout=20,
        )
        assert me.status_code == 200, f"GET /me: {me.status_code} {me.text[:200]}"
        assert me.json().get("permissions"), (
            "the persona has no permissions either, so a 403 would not prove anything about "
            "tenant scoping"
        )

    # Parametrized on the SHAPE of each endpoint, not on a literal path: the collection comes from
    # the fixture, which a parametrize list evaluated at collection time cannot reach. `send_body`
    # says whether the verb takes one; the body itself is the entity's own required fields, so a
    # module whose create needs more than a name is still exercised with a payload its API accepts.
    @pytest.mark.parametrize("method,suffix,send_body", [
        ("GET", "", False),
        ("GET", "/1", False),
        ("POST", "", True),
        ("PUT", "/1", True),
        ("DELETE", "/1", False),
        ("GET", "/1/history", False),
    ])
    def test_every_data_endpoint_denies(self, no_tenant, entity_api, marker, method, suffix,
                                        send_body):
        path = f"{entity_api.collection}{suffix}"
        body = entity_api.create_body(f"{marker}-should-never-exist") if send_body else None
        response = no_tenant.session.request(
            method, f"{no_tenant.api_base_url}{path}", json=body, timeout=TIMEOUT,
        )
        assert response.status_code == 403, (
            f"{method} {path} answered {response.status_code}, not 403 — a token with no tenant "
            f"claim is a misconfiguration and must be an outage, not a breach. {response.text[:200]}"
        )
        assert "tenant" in response.text.lower(), response.text[:200]


class TestTwoTenantIsolation:
    """Two tenants, two tokens, and neither may see the other."""

    def test_each_tenant_sees_only_its_own_item(self, tenant_a, tenant_b, entity_api, item_a,
                                                item_b):
        a_ids, b_ids = tenant_a.row_ids(entity_api), tenant_b.row_ids(entity_api)
        assert item_a["id"] in a_ids and item_b["id"] not in a_ids, (
            f"A sees {a_ids}; B's item {item_b['id']} must not be among them"
        )
        assert item_b["id"] in b_ids and item_a["id"] not in b_ids, (
            f"B sees {b_ids}; A's item {item_a['id']} must not be among them"
        )

    def test_the_id_filter_does_not_bypass_the_scope(self, tenant_a, entity_api, item_b):
        """Asking for the id directly is the shortest path around a list filter."""
        assert tenant_a.row_ids(entity_api, id=item_b["id"]) == set()

    def test_get_by_id_is_404_not_403(self, tenant_a, entity_api, item_b):
        """403 would confirm the id exists somewhere — an enumeration side channel."""
        response = tenant_a.get(f"{entity_api.collection}/{item_b['id']}")
        assert response.status_code == 404, f"{response.status_code} {response.text[:200]}"

    def test_put_another_tenants_item_is_404(self, tenant_a, entity_api, marker, item_b):
        response = tenant_a.put(f"{entity_api.collection}/{item_b['id']}",
                                json=entity_api.update_body(f"{marker}-taken-over"))
        assert response.status_code == 404, f"{response.status_code} {response.text[:200]}"

    def test_delete_another_tenants_item_is_404(self, tenant_a, entity_api, item_b):
        response = tenant_a.delete(f"{entity_api.collection}/{item_b['id']}")
        assert response.status_code == 404, f"{response.status_code} {response.text[:200]}"

    def test_history_of_another_tenants_item_is_404(self, tenant_a, entity_api, item_b):
        response = tenant_a.get(f"{entity_api.collection}/{item_b['id']}/history")
        assert response.status_code == 404, f"{response.status_code} {response.text[:200]}"

    def test_b_is_untouched_by_all_of_that(self, tenant_b, entity_api, item_b):
        """A 404 that still modified the row would be worse than a 200.

        Compared field by field against what B created, rather than on one named column: the row's
        fields are the module's, and asserting on `name` would only work for a module that has one.
        """
        response = tenant_b.get(f"{entity_api.collection}/{item_b['id']}")
        assert response.status_code == 200, response.text[:200]
        assert response.json() == item_b, "the row B created came back changed"


class TestWritesAreScoped:

    #: The marker suffix the create below carries, so the next test can look for exactly it.
    SMUGGLED = "smuggled"

    def test_naming_another_tenant_on_create_is_403(self, tenant_a, entity_api, marker):
        """403, not 404: the caller named the tenant, so it learns nothing it did not assert."""
        body = {**entity_api.create_body(f"{marker}-{self.SMUGGLED}"), "tenant_id": TENANT_B}
        response = tenant_a.post(entity_api.collection, json=body)
        assert response.status_code == 403, f"{response.status_code} {response.text[:200]}"

    def test_nothing_was_written_to_the_other_tenant(self, tenant_b, entity_api, marker):
        """Searched by the marker in ANY string field, because the module names its own columns.

        The marker is a fresh uuid per run and this suite writes it into every required string
        field, so a row carrying it in any of them is this suite's and nobody else's.
        """
        needle = f"{marker}-{self.SMUGGLED}"
        rows = tenant_b.get(entity_api.collection, params={"limit": 200}).json()[entity_api.list_key]
        assert not [
            row for row in rows
            if any(isinstance(v, str) and needle in v for v in row.values())
        ], f"a row created as tenant A carrying {needle!r} is visible to tenant B"

    def test_an_omitted_tenant_id_resolves_to_the_callers_own(self, tenant_a, entity_api, marker):
        """Requiring clients to echo back their own tenant mostly invites them to send another's."""
        created = tenant_a.create_row(entity_api, f"{marker}-implicit")
        try:
            assert created["tenant_id"] == TENANT_A
        finally:
            tenant_a.delete(f"{entity_api.collection}/{created['id']}")

    def test_naming_the_callers_own_tenant_is_accepted(self, tenant_a, entity_api, marker):
        created = tenant_a.create_row(entity_api, f"{marker}-explicit", tenant_id=TENANT_A)
        try:
            assert created["tenant_id"] == TENANT_A
        finally:
            tenant_a.delete(f"{entity_api.collection}/{created['id']}")


class TestCrossTenantReadIsExplicitAndReadOnly:
    """The one sanctioned way to see another tenant's data — and its limits."""

    def test_the_permission_is_actually_held(self, cross_reader, hostapp_api_url):
        """If the authorization contract was never seeded, the rest of this class would pass for
        the wrong reason (a reader that sees nothing looks like a reader that is correctly scoped).

        Read from host_app rather than from the token: the token is thin, and the remote backend
        resolves this permission the same way -- so this asserts the exact value the code under
        test will see.
        """
        me = requests.get(
            f"{hostapp_api_url}/me", headers={"Authorization": f"Bearer {cross_reader.token}"},
            timeout=20,
        )
        assert me.status_code == 200, f"GET /me: {me.status_code} {me.text[:200]}"
        granted = set(me.json().get("permissions") or [])
        assert CROSS_TENANT_PERMISSION in granted, (
            f"the persona holds {sorted(granted)} — the cross-tenant role has not been seeded; "
            f"run ./authz.sh seed --force"
        )

    def test_reads_are_widened(self, cross_reader, entity_api, item_a, item_b):
        ids = cross_reader.row_ids(entity_api)
        assert {item_a["id"], item_b["id"]} <= ids, (
            f"a cross-tenant reader sees {ids}, missing one of {item_a['id']}, {item_b['id']}"
        )

    def test_get_by_id_across_tenants_succeeds(self, cross_reader, entity_api, item_b):
        response = cross_reader.get(f"{entity_api.collection}/{item_b['id']}")
        assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
        assert response.json()["tenant_id"] == TENANT_B

    def test_history_across_tenants_is_real_not_synthetic(self, cross_reader, entity_api, item_b):
        """A widened read that returned no version rows would render the synthetic "created" row:
        a record with a real history would look like one that had never changed."""
        response = cross_reader.get(f"{entity_api.collection}/{item_b['id']}/history")
        assert response.status_code == 200, f"{response.status_code} {response.text[:200]}"
        rows = response.json()[entity_api.list_key]
        assert rows, f"no history at all for a {_ENTITY} row that was just created"
        assert all(row["id"] == item_b["id"] for row in rows)

    def test_put_across_tenants_is_still_404(self, cross_reader, entity_api, marker, item_b):
        """Granting visibility must not grant authority."""
        response = cross_reader.put(f"{entity_api.collection}/{item_b['id']}",
                                    json=entity_api.update_body(f"{marker}-widened-write"))
        assert response.status_code == 404, f"{response.status_code} {response.text[:200]}"

    def test_delete_across_tenants_is_still_404(self, cross_reader, entity_api, item_b):
        response = cross_reader.delete(f"{entity_api.collection}/{item_b['id']}")
        assert response.status_code == 404, f"{response.status_code} {response.text[:200]}"

    def test_create_into_another_tenant_is_still_403(self, cross_reader, entity_api, marker):
        body = {**entity_api.create_body(f"{marker}-widened-create"), "tenant_id": TENANT_B}
        response = cross_reader.post(entity_api.collection, json=body)
        assert response.status_code == 403, f"{response.status_code} {response.text[:200]}"

    def test_the_other_tenants_item_survived(self, tenant_b, entity_api, item_b):
        response = tenant_b.get(f"{entity_api.collection}/{item_b['id']}")
        assert response.status_code == 200, response.text[:200]
        assert response.json() == item_b, "the row B created came back changed"


class TestRowLevelSecurityAlone:
    """Isolation with the application's filter removed — the layer that survives a mistake."""

    def test_the_application_role_cannot_bypass_rls(self, app_role_db):
        rows, _ = _as_tenants(app_role_db, [TENANT_A], """
            SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user
        """)
        assert rows[0] == (False, False), (
            "the application connects as a role that bypasses RLS — the policies are decorative"
        )

    def test_rls_is_enabled_and_forced_on_every_scoped_table(self, app_role_db):
        rows, _ = _as_tenants(
            app_role_db, [TENANT_A],
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relname = ANY(%s) ORDER BY relname",
            ([ENTITY_TABLE, ENTITY_VERSION_TABLE],),
        )
        assert rows == sorted([
            (ENTITY_TABLE, True, True), (ENTITY_VERSION_TABLE, True, True),
        ]), f"{rows} — without FORCE the owner is exempt even when it is not a superuser"

    def test_an_unfiltered_query_still_returns_only_one_tenant(
        self, app_role_db, item_a, item_b
    ):
        """The automated form of "comment out the filter in crud.list_items".

        No tenant predicate at all — which is precisely what a commented-out filter produces — and
        the answer must still be one tenant's rows.
        """
        rows, _ = _as_tenants(
            app_role_db, [TENANT_A],
            f"SELECT id, tenant_id FROM {ENTITY_TABLE} WHERE id = ANY(%s)",
            ([item_a["id"], item_b["id"]],),
        )
        assert [r[0] for r in rows] == [item_a["id"]], (
            f"an unfiltered query returned {rows} — RLS is not carrying the isolation on its own, "
            f"so a future query that forgets its filter is a leak"
        )

    def test_the_same_holds_for_the_history_table(self, app_role_db, item_a, item_b):
        rows, _ = _as_tenants(
            app_role_db, [TENANT_A],
            f"SELECT DISTINCT tenant_id FROM {ENTITY_VERSION_TABLE} WHERE id = ANY(%s)",
            ([item_a["id"], item_b["id"]],),
        )
        assert {r[0] for r in rows} <= {TENANT_A}, f"history leaked tenants {rows}"

    def test_no_tenant_setting_returns_nothing(self, app_role_db, item_a, item_b):
        """current_setting(..., true) is NULL when unset, and NULL matches no rows."""
        rows, _ = _as_tenants(
            app_role_db, None,
            f"SELECT id FROM {ENTITY_TABLE} WHERE id = ANY(%s)",
            ([item_a["id"], item_b["id"]],),
        )
        assert rows == [], f"a session that never said who it is saw {rows}"

    def test_the_cross_read_policy_does_not_widen_an_update(self, app_role_db, entity_api, marker,
                                                            item_b):
        """The widening is FOR SELECT, so it cannot authorise a write even at the database.

        The column written is one of the entity's own required create fields, so this is a real
        UPDATE of a real column in any module — `name` was the template's, and nobody else's.
        """
        column, value = next(iter(entity_api.create_body(f"{marker}-at-the-db").items()))
        _, count = _as_tenants(
            app_role_db, [TENANT_A],
            f"UPDATE {ENTITY_TABLE} SET {column} = %s WHERE id = %s",
            (value, item_b["id"]), cross_read=True,
        )
        assert count == 0, f"{count} row(s) updated across tenants with only a read permission"

    def test_the_cross_read_policy_does_not_widen_a_delete(self, app_role_db, item_b):
        _, count = _as_tenants(
            app_role_db, [TENANT_A],
            f"DELETE FROM {ENTITY_TABLE} WHERE id = %s",
            (item_b["id"],), cross_read=True,
        )
        assert count == 0, f"{count} row(s) deleted across tenants with only a read permission"

    def test_inserting_into_another_tenant_is_refused_by_the_policy(self, app_role_db, entity_api,
                                                                    marker):
        """Columns and values from the entity's own required create fields.

        The API's required create fields ARE the entity's NOT NULL columns, so an INSERT built from
        them is a valid one for any module — while `(tenant_id, name)` was valid only for a module
        that happens to have a `name`.
        """
        fields = entity_api.create_body(f"{marker}-db-smuggled")
        fields.pop("tenant_id", None)
        columns = ", ".join(["tenant_id", *fields])
        placeholders = ", ".join(["%s"] * (1 + len(fields)))
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            _as_tenants(
                app_role_db, [TENANT_A],
                f"INSERT INTO {ENTITY_TABLE} ({columns}) VALUES ({placeholders})",
                (TENANT_B, *fields.values()), cross_read=True,
            )
        app_role_db.rollback()


def _function_source(text: str, name: str) -> str:
    """One top-level function's source, bounded by the NEXT top-level `def`.

    Paired with the `code_only` fixture from the repo-root `conftest.py`: this slices, that strips
    the comments and docstrings, and the assertion is then about code. Both halves are needed —
    the docstrings in `crud.py` explain *why* a write ignores the cross-tenant read permission, so
    a raw search finds `read_all_tenants` in the explanation and calls it the violation.

    Bounded structurally rather than by naming the function that follows it. The function after
    `_resolve_write_tenant` in `crud.py` is the ENTITY's own create wrapper — `create_item` here,
    `create_company` in a module whose entity is companies — so slicing to a literal
    `"def create_item("` raised `ValueError: substring not found` in every remote module, in a
    force-synced file the module cannot edit.
    """
    start = text.index(f"def {name}(")
    following = re.search(r"^def \w+\(", text[start + 1:], re.M)
    return text[start:start + 1 + following.start()] if following else text[start:]


class TestTheApplicationFilterIsStillThere:
    """RLS is the second layer, not the only one — a test that passes on RLS alone must not be
    read as permission to drop the filter."""

    def test_reads_filter_on_the_readable_tenants(self):
        crud = (_APP / "crud.py").read_text(encoding="utf-8")
        assert "tenant_id.in_(scope.tenant_ids)" in crud

    def test_writes_resolve_against_the_callers_own_tenants_only(self, code_only):
        crud = (_APP / "crud.py").read_text(encoding="utf-8")
        code = code_only(_function_source(crud, "_resolve_write_tenant"))
        assert "scope.tenant_ids" in code
        assert "read_all_tenants" not in code, (
            "a write must never consult the cross-tenant READ permission"
        )

    def test_loading_a_row_for_writing_ignores_the_cross_tenant_read_widening(self, code_only):
        """A caller that may SEE every tenant's rows must still write only to its own.

        `get_entity(..., for_write=True)` is how PUT and DELETE load their target, and it filters on
        `scope.tenant_ids` rather than going through the readable-tenants helper. Collapsing the two
        would let one customer's administrator edit another's data.

        This test exists because the parameter was nearly lost. Factoring crud.py into
        model-parameterised helpers dropped `for_write` from the generic `get_entity`, and only
        mypy noticed — via a call-site signature, not the security property. A type checker is the
        wrong last line of defence for this, so the property is asserted directly.
        """
        crud = (_APP / "crud.py").read_text(encoding="utf-8")
        code = code_only(_function_source(crud, "get_entity"))
        assert "for_write" in code, (
            "get_entity no longer distinguishes a read from a write load — PUT and DELETE would "
            "then resolve their target through the cross-tenant READ widening"
        )
        assert "tenant_id.in_(scope.tenant_ids)" in code, (
            "the write path does not filter on the caller's OWN tenants"
        )

    def test_the_scope_cannot_be_constructed_empty(self):
        auth = (_APP / "auth.py").read_text(encoding="utf-8")
        assert "TenantScope requires at least one tenant id" in auth

    def test_the_claim_parser_accepts_the_canonical_format(self):
        """`TenantName(ID)` is what host_app writes; parsing only integers denied everyone."""
        auth = (_APP / "auth.py").read_text(encoding="utf-8")
        assert "_TENANT_TAGGED_RE" in auth
