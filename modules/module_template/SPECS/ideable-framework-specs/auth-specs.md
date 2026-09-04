# module_template Authentication & Authorization Specification

## 1. Purpose and Scope

This document mirrors `modules/host_app/SPECS/auth-specs.md` and defines the **mandatory** authentication and authorization contract for any remote module derived from module_template. Keeping this file in sync across host_app ⇄ module_template ⇄ downstream remotes ensures:

1. Auth rules are discoverable without digging into host_app internals.
2. Template sync tooling can propagate spec changes automatically.
3. The stricter `:menu_access` permission model stays consistent everywhere.

Whenever host_app’s `auth-specs.md` changes, **update this file in the same change set** and re-sync module_template derived repos.

---

## 2. Identity Provider & Session Model

- **Authentik** is the only identity provider and JWT issuer.
- The SPA and backend authenticate exclusively via **OIDC Authorization Code Flow + PKCE**.
- Access tokens are validated as Bearer JWTs against Authentik JWKS; local key stores or static secrets are forbidden.
- Reject missing, expired, malformed, unsigned, or signature-invalid tokens with `401`.
- Remote modules MUST NOT implement standalone login flows, password databases, or token minting helpers.
- The backend never accepts raw credentials—only Bearer tokens obtained from Authentik.

---

## 3. JWT Claim Contract

**The token carries identity and NOTHING else.** No permissions, no roles, no profiles, no active
profile — and, since the tenant scope moved to `/api/me`, no tenant ids either. Anything that needs
to know what a caller may do, or whose data they may do it to, asks host_app.

Tenancy was the last authorization value in the token, and it left for the reason all the others
did. It reached a module as a claim rendered from an Authentik user attribute that host_app wrote:
three hops with no end-to-end check. The middle hop failed silently once, no admin's scope was ever
written, and every tenant-scoped module answered 403 — while the token still looked well-formed.

### 3.1 Namespaces

| Namespace | Purpose |
| --- | --- |
| standard OIDC (`sub`, `preferred_username`, `email`, `name`) | Who this is. Emitted by Authentik's default scope mappings. |

That is the whole contract — standard OIDC identity claims, and no namespace of ours at all.
Namespaces that existed before and MUST NOT be reintroduced: `hostapp.permissions`,
`<module_slug>.permissions`, `<module_slug>.roles`, `hostapp.active_profile`, `hostapp.tenant_ids`.

### 3.2 Where authorization comes from instead

`GET {HOSTAPP_API_URL}/api/me`, with the caller's bearer token, answers both halves at once:

| Field | Purpose |
| --- | --- |
| `permissions` | What the caller may do. |
| `tenant_ids` | Whose data they may do it to. Entries use `TenantName(ID)` and MUST be honored for multi-tenant filtering. |

One call, cached per token for `PERMISSION_CACHE_TTL_SECONDS`, which is host_app's published
revocation SLO. A change upstream stops being honored within that window — a token claim, by
contrast, stayed true until the token expired.

### 3.2 Why

Three reasons, each measured rather than asserted:

1. **Size.** At two enabled modules the token was 2,401 bytes, with permission arrays 49% of the
   claims at ~22 bytes each. ~76 more permissions — two or three more modules the size of
   module_template — reached a common 4 KB header limit. Token size now does not track the
   permission model at all.
2. **Revocation.** A permission removed from a role used to keep working until the current access
   token expired (300 s, by provider configuration). It now stops within a **60 s SLO**, and so does
   disabling a user — which is the half an auditor asks about.
3. **Correctness.** Deriving permissions inside the IdP's sandboxed property-mapping expression
   failed silently twice in this project: once because a helper it relied on did not exist, serving
   every user a stale permission set for the life of the system, and once because a name-keyed
   permission catalogue collided across modules. Both produced well-formed tokens.

### 3.3 How a permission check is answered

- **host_app backend**: `require_permission()` resolves from host_app's own tables through an
  in-process per-replica cache validated by a Postgres `authz_generation` counter. It MUST NOT call
  the identity plane on the request path — that plane is CPU-bound at ~6.3 logins/s.
- **Remote module backend**: `require_permission()` calls host_app's `GET /api/me` with the caller's
  bearer token and caches the answer per token for 60 s (the revocation SLO). It MUST NOT read
  permissions from claims: a thin token carries none, so a claim reader denies everything — or,
  mid-upgrade, honours a stale set.
- **Any frontend**: `GET /api/me`. It returns `permissions` (fully qualified
  `<module_slug>.<resource>:<action>`), `active_profile` and `user_profiles`. A frontend MUST NOT
  decode the token for authorization.

Failure is **fail-closed and distinguishable**: when resolution is unavailable the answer is `503`
("cannot decide"), never `403` ("decided no") and never an empty permission set, which would render
a working application with everything hidden and no explanation.

### 3.4 Example payload fragment

```json
{
  "sub": "b3c1…",
  "preferred_username": "sadmin",
  "email": "sadmin@ideable.tech"
}
```

---

## 4. Authorization Configuration (`config/authorization.yaml`)

- Serves as the authoritative contract consumed by `bootstrap_authentik.py`.
- MUST declare every permission the module requires using `<resource>:<action>` names, including `<resource>:menu_access`.
- Role↔permission and profile↔role mappings are optional but MUST follow the host_app schema when present.
- `authorization.yaml` is a **seed**, not a live control surface. It states the permissions, roles and
  profiles the module requires, and the associations between them that the module needs in order to
  work. It is applied **once per module contract version** — see §8.1.
- **Changing it does NOT require a redeploy to take effect at runtime.** Permissions, roles, profiles and
  their associations are administered through the Ideable UI/API after seeding, and a change there is
  reflected in the next token issued. Shipping a new module version is how a module changes what it
  *requires*, not how an operator changes what is *granted*.

---

### 5. Frontend Responsibilities

1. Read the permission set from `GET /api/me`. It arrives already fully qualified as
   `<module_slug>.<resource>:<action>`. Resolve every visibility and action check by exact match
   against it (e.g. check for `"<slug>.<entity>:menu_access"`). A frontend MUST NOT decode the access
   token for authorization: it carries no permissions, and a profile switch takes effect on the next
   `/me` rather than on the next token.
2. `authorization_claim` entries in `menu_definition.json` remain bare `<resource>:menu_access` strings and MUST reference real permissions the module declares in `config/authorization.yaml`; the module context supplies the prefix at match time.
3. Hide or disable all UI actions (buttons, table actions, edit icons, routes) when the matching permission is absent.
4. Refresh the in-memory permission map from `/me` on profile change and on token renew. A profile switch does **not** need a new token: the active profile is a host_app column, so the next `/me` already reflects it.
5. Treat `<resource>:menu_access` as visibility only; never infer edit rights from it.
6. Treat `audit_trail:view` as the authority for audit-trail row actions and popup access.

---

## 6. Backend Responsibilities

1. Apply a central dependency (see module_template `backend/SOURCES/app/auth.py`) to parse JWTs and expose helpers like `require_permission("<slug>.<entity>:view")`.
2. Every protected endpoint MUST validate the bearer token; return `401` for missing/invalid tokens and `403` for authenticated-but-unauthorized callers.
3. CRUD routes MUST declare explicit permissions (e.g., `<slug>.<entity>:view` for `GET`, `<slug>.<entity>:edit` for `POST/PUT/DELETE`).
4. Never trust UI hints or query params. Authorization comes from host_app's authorization tables — resolved locally in host_app, and via `GET /api/me` in a remote module — never from the token and never from a module's own tables.
5. Enforce tenant scoping using the `tenant_ids` from `/api/me` on every data access.
6. History endpoints for audit-trail access MUST require `<module_slug>.audit_trail:view` and MUST return `403` when that permission is missing.

### Permission string format

`config/authorization.yaml` declares permissions as bare `<resource>:<action>` strings (e.g. `items:view`); the declaring module's slug qualifies them, so the stored and resolved form is always `<module_slug>.<resource>:<action>`. **No permission exists without its owning module** — a name alone is ambiguous, because several modules legitimately declare `audit_trail:view`. All `require_permission()` calls MUST pass the fully-qualified form. Bare `<resource>:<action>` strings to `require_permission()` are never correct, and a contract test (`test_permission_names_declared.py`) fails the build when a name reaching `require_permission()` is not declared anywhere — such a typo otherwise denies silently.

---

## 7. Menu Definition Alignment

- `config/menu_definition.json` and host_app’s `modules_menu_mapping.json` use bare `authorization_claim` strings that MUST equal `<resource>:menu_access` permissions; each `modules_menu_mapping.json` item also carries a `module` field.
- host_app qualifies each `authorization_claim` with its item's `module` prefix (`<module>.<resource>:menu_access`) and renders the entry only when that fully-qualified permission is in the set `/me` returned.
- Parent/section items that control collapsible groups require their own `<resource>:menu_access` entry.
- host_app will never render a menu entry unless the qualified permission is present; remote SPAs must mirror this logic against their own flattened token.

---

## 8. Where authorization lives

**host_app's database owns the authorization model.** Authentik owns identity. These were the same
store until the authorization rework, and conflating them is the root cause behind Tasks 15, 16a and 16b.

| Concern | Owner | Where |
| --- | --- | --- |
| Credentials, MFA, sessions, the login flow | Authentik | Authentik's database |
| Group membership **as delivered by a customer directory** | Authentik | Authentik's database |
| Authentik's own admin RBAC (the `hostapp-api` service account) | Authentik | Authentik's database |
| Permissions, roles, profiles, and their associations | host_app | `permissions`, `roles`, `profiles`, `role_permissions`, `profile_roles`, `user_profiles` |
| Which profile a user is acting under | host_app | `users.active_profile_fk` |
| Directory group → profile translation | host_app | `directory_group_profiles` |
| What the seed applied, and what it deliberately did not | host_app | `module_seed_state`, `module_seed_requirements`, `system_messages` |

The distinction that matters: a **directory group is a fact about a person**, delivered by their
employer's IdP. An **Ideable profile is a grant**. One explicit mapping table translates between
them, and a module MUST NOT assume the two are the same object.

Consequences a module must honour:

- Authentik holds **no** Ideable profiles, roles or permission registries. Code that reads them does
  not work and must not be written.
- A remote module MUST NOT write authorization anywhere itself. It declares what it needs in
  `config/authorization.yaml`; host_app's seed applies it (§8.1).
- A permission decision MUST NOT be cached beyond the **60 s revocation SLO**. host_app validates its
  cache against a Postgres generation counter, so it is usually sub-second; a remote module caching
  `/me` MUST bound its own cache at 60 s.
- host_app's database and Authentik's database MUST be backed up and restored **together**. They
  reference each other (`users.authentik_internal_id`), so restoring one alone leaves the pair
  inconsistent — see `docs/RUNBOOK.md`.

### 8.1 Seed lifecycle (mandatory)

The seed runs **once per module contract version**, never on a restart.

- The trigger is a hash of the module's normalized `authorization.yaml`. `module.json`'s `version` and
  the build-time `buildDateTime` are recorded alongside it for traceability, but they do not gate the
  seed: during development a module is conceptually "latest" and a version bump is the step that gets
  forgotten.
- A plain restart of the stack writes **no** authorization data. Before this contract existed, the
  bootstrap rebuilt every registry from every module's YAML on each start, silently reverting whatever
  an operator had configured.
- The seed is applied by **host_app's backend**, which owns the database — at startup, and on demand.
- Seeding outside a version change requires an explicit operator action, available at a deployed site
  with no redeploy and no rebuild: `./authz.sh seed [--module <name>] [--force] [--dry-run]`.

`config/authorization.yaml` declares **permissions, roles, profiles and the associations the module
requires — not users.** People arrive from the customer's directory (federation, JIT, or the periodic
sync), or through self-registration with approval; declaring them in a file that ships inside an image
would make onboarding one person need a build and a redeploy, which at a production site is not
possible at all. A fresh install's first administrator and the fixed test personas live in
`config/bootstrap-users.yaml`, which is ignored entirely once `BOOTSTRAP_USERS_ENABLED=false`.

**A module owns its own permissions, roles and profiles.** An operator may attach a module's roles to
profiles the module did not define, and a module's permissions to roles the module did not define. That
is expected and supported. **Editing the entities and associations a module declares is discouraged**,
because the module's next version states its requirements again.

**How a re-seed treats what it finds** — the seed states what it *requires*, not the total desired state:

| Found in the live state | Result |
|---|---|
| A required association is present | Nothing to do |
| Extra associations an operator added | **Kept.** Never removed |
| A required association is absent and was never seeded before | **Applied** — new in this version, no operator decision is being overridden |
| A required association is absent but was present in a previous seed | The operator removed it deliberately. **The removal is respected, not undone**, and a message is recorded in **Admin → System messages** stating that the module still expects it |

A seed can therefore only ever add associations that have never been seeded. It cannot restore a
revoked permission and cannot reduce a deployment's security posture. When a module appears not to work
after an upgrade, **Admin → System messages** is where the reason is.

---

## 9. Compliance Checklist

A remote module is compliant only if the answer to each question is “yes”:

1. Does the SPA/backend authenticate exclusively via Authentik OIDC Authorization Code + PKCE?
2. Does every API call resolve authorization from host_app (`GET /api/me`), with no local RBAC fallback and no permission read from the token?
3. Are menu entries rendered only when the fully-qualified `<module_slug>.<resource>:menu_access` permission is present in the set `/me` returned?
4. Are CRUD actions gated by explicit `<resource>:view|edit|delete|...` permissions defined in `config/authorization.yaml`?
5. Is bootstrap rerun (via redeploy) whenever permissions/roles/profiles change?
6. Is tenant scoping enforced from `/api/me`'s `tenant_ids`?
7. Are this file and host_app `SPECS/auth-specs.md` kept in sync across host_app, module_template, and downstream remotes?

Any “no” answer means the module is out of spec and must not ship.

---

## 10. Sync Policy

- `modules/module_template/SPECS/ideable-framework-specs/auth-specs.md` is part of the **shared spec set** and MUST be distributed to every derived module.
- Update `scripts/module_only/sync-template-updates.sh` and `scripts/master_only/push-updates-to-module_template-repo.sh` whenever new shared specs are added so that consumer repos automatically receive them.
- Derived modules MAY extend this document with stricter module-specific requirements, but they MUST keep the shared sections identical to the baseline to remain compatible with host_app expectations.


## 11. Changes in the authentication and authorization specifications

When during the development of a module changes are needed or suppoesed to be needed to the authentication and authorization specifications, the following steps MUST be taken:
1. Never modify modules/host_app/authentik/DIST/bootstrap_authentik.py file. It is a Framework managed file that should not be modified by any module.
2. Create a concise and complete description of the issue and the proposed solution.
3. Send a chage request to the Ideable Framework team, or ask for assistance to the Ideable Framework team.

## Tenant scoping (mandatory, and how it is enforced)

§5.5 requires tenant scoping on every data access. The template now implements it, and a derived
module must keep all four layers — each one covers a different way the others fail.

1. **Source.** Tenant ids come from `/api/me`, parsed by `auth.tenant_ids_from()` — the same cached
   resolution that yields permissions, so the two halves of one decision can never disagree.
   They are a data-isolation dimension, not an action. Flattened in with permissions they became
   strings like `template.7` that no check ever matched, while implying the claim was handled.

   **Parse the canonical `TenantName(ID)` form** (§3), not only bare integers. That is what
   host_app writes — `DEFAULT_TENANT(1)` on a fresh installation, and the customer's own tenant
   names anywhere else — and a reader that accepted only `1` dropped every id as
   non-numeric, so `require_tenant_scope()` denied every request in the installation. Fail-closed
   then hid the bug perfectly: a 403 looks identical whether the claim is missing or unreadable.
   Match on the id in parentheses and ignore the name; names are editable labels, and matching one
   would follow a rename into the wrong tenant.
2. **Fail closed.** `require_tenant_scope()` returns 403 when the scope is absent, empty or
   malformed, and 503 when host_app cannot be reached. Never fall back to "all tenants", and never
   fall back to a cached or token-borne value: a misconfiguration must be an outage, not a breach,
   and a stale scope honored after an administrator changed it is the breach.
3. **Query scoping.** Every read filters on `tenant_id`; every write validates the target tenant.
   `get_item` returns **404, not 403**, for another tenant's row — a 403 confirms the id exists
   somewhere, which is an enumeration side channel.
4. **Row-Level Security.** Policies on the tables plus `set_config('app.tenant_ids', …, true)` per
   transaction, so a query that forgets its filter still returns nothing.
5. **A declared tenancy marker on every model.** `__tenant_scoped__ = True | False`, enforced at
   build time by `scripts/common/check_tenancy_markers.py` (run from
   `scripts/common/validate_modules.sh`). `True` also requires the `tenant_id` column to exist.
   The first four layers protect the tables someone remembered; this one is about the next table.
   A model added without `tenant_id` raises nothing, logs nothing and fails no test — it simply
   holds every customer's rows while the queries over it look correct — so silence is not an
   allowed answer. `False` is legitimate for reference data, a framework ledger or a control-plane
   table; state it, with the reason, next to the model.

### The one sanctioned way to read across tenants

An administrator who must see every tenant's data gets **their own tenant plus a named
permission** — in the template, `<slug>.<entity>:read_all_tenants`, declared in
`config/authorization.yaml` and granted to host_app's application-wide `admin` profile, not to the
module's own `template_admin` (which administers one tenant's items).

Not a superadmin branch, and not an early return. An implicit "administrators see everything" is
invisible three times over: absent from the code path a reviewer reads, absent from the token an
operator inspects, and absent from the authorization contract an auditor is handed. It also cannot
be granted to one person — whoever later holds the same role inherits it silently.

Three properties make the widening safe, and a derived module must keep all three:

- **The fail-closed gate runs first.** A caller with the permission and no tenant of its own is
  still denied. The permission widens a scope; it does not conjure one.
- **Reads only, at BOTH layers.** `auth.TenantScope` carries `tenant_ids` (never widened) and
  `read_all_tenants` separately; writes always resolve against `tenant_ids`. At the database, the
  widening is a second policy that is `FOR SELECT` — permissive policies are OR-ed per command, so
  it cannot authorise an UPDATE, DELETE or INSERT. Verified against the policies: `UPDATE 0`,
  `DELETE 0`, and a cross-tenant INSERT refused outright. Granting visibility must not grant
  authority.
- **PUT and DELETE load their target as a write** (`crud.get_item(..., for_write=True)`), so a
  cross-tenant reader still gets 404 rather than loading the row and being stopped by the policy —
  which would surface as a 500 where the honest answer is "not yours".

#### Naming the cross-tenant entity: one token by default, declared when it cannot be

The entity named by `<entity>:read_all_tenants` is referred to by **three** naming systems, and the
tenancy acceptance suite has to line them up before it can exercise anything:

| Name | Where it lives | Read from |
|---|---|---|
| the permission entity | `config/authorization.yaml` | `<entity>:read_all_tenants` |
| the collection route segment | the backend's routers | the running backend's `/openapi.json` |
| the table | `backend/SOURCES/app/models.py` | `__tablename__`, with the module's db prefix |

**By default all three are the same token.** In this module that is `items` / `/items` /
`template_items`, and most modules will match it. A module that does needs to declare nothing.

**When they cannot be, declare the mapping — do not rename to satisfy the suite.** Requiring a
public REST collection path to equal a database table name is a coupling the framework does not
impose: kebab-plural routes over snake-singular tables is ordinary, defensible REST, and a module
with it satisfies neither derivation. Add to `modules/<MODULE>/module.json`:

```jsonc
{
  "crossTenantEntity": {
    "collectionRoute": "/assessments",   // the POST collection, as the API serves it
    "table": "sra_assessments"           // the __tablename__, exactly as models.py declares it
  }
}
```

Either key may be omitted; the convention fills in whatever is not declared.

**Where a disagreement surfaces, and what it says.** Two of the three names are checked before the
build, by `validate_cross_tenant_entity_naming` in `scripts/common/validate_modules.sh`: the
permission entity against `__tablename__`. The route cannot be checked there — it comes from a
running backend — and the validation error **says so** rather than implying it verified three. The
route half is checked by `backend/TESTS/test_tenant_isolation.py`, which reports it as **one**
failure naming all three names: its entity resolution is deliberately lazy, so a naming
disagreement is a single readable assertion plus honest skips, not a collection error that turns
every test in the file red with nothing to read.

### Two things that make RLS decorative if you get them wrong

**The application must not connect as the database owner.** The owner is a superuser, and
superusers bypass RLS unconditionally. During this work RLS was enabled *and* forced, and a session
set to tenant 1 still returned tenant 2's rows. The backend connects as a `NOSUPERUSER NOBYPASSRLS`
role — `<PREFIX>_APP_DB_USER` in `.env.config`, `<PREFIX>_APP_DB_PASSWORD` in `.env.secrets`, named
by the backend's `DATABASE_URL` and by nothing else; migrations keep the owner, which needs DDL.

**That role is created by the bootstrap job**, after the migrations and before the backend, in the
force-synced `bootstrap-service` block of the module's `docker-compose.yml`. The step, its grants,
and why it is neither an `initdb` script nor a migration are specified in
`database/SPECS/ideable-framework-specs/schema-workflow.md` § *The application role*. A remote
module authors none of it: a bootstrap job without `CREATE ROLE` in it predates the contract and
`scripts/module_only/sync-template-updates.sh` brings it in.

**`FORCE ROW LEVEL SECURITY`, not just `ENABLE`.** Without FORCE the owner is exempt even when not
a superuser.

### Two consequences of RLS that break working code

**A write needs the GUC too, not just a read.** The policy governs INSERT as well as SELECT, so a
create path that never published `app.tenant_ids` did not merely skip a layer — it could not write
at all (`new row violates row-level security policy`). Publish the scope before the flush.

**`set_config(…, true)` is transaction-local, so a post-commit read needs it again.** `db.commit()`
ends the transaction the setting was scoped to, and `Session.refresh` then issues its SELECT in a
new one, where the row is invisible and the refresh raises. Re-publish before reading back. This is
the price of the property that stops the setting leaking to the next request on a pooled
connection, so it is the right trade — but it has to be paid explicitly.

### Indexing

`tenant_id` leads the composite indexes. Isolation bolted on top of an existing index scans every
tenant's rows and filters afterwards, which gives back the query gains it was tuned for.

### Verification checklist for a derived module

- [ ] Token without a tenant claim → 403 on every data endpoint.
- [ ] Another tenant's id → 404 on GET, PUT, DELETE and history.
- [ ] The deployed backend's `DATABASE_URL` names `<PREFIX>_APP_DB_USER`, not the owner, and `\du`
      reports that role with neither `Superuser` nor `Bypass RLS`. Read it from the running
      container's own environment: an unexpanded `${…}` in an env file yields an empty password,
      not an error.
- [ ] Connecting to the database directly as the application role with `app.tenant_ids` set to A
      returns none of B's rows — and returns nothing at all when the setting is absent.
- [ ] Comment out the tenant filter in one query: the isolation test must still pass, on RLS alone.
      In an automated suite, run the query with **no tenant predicate at all** as the application
      role — that is what a commented-out filter produces, and it needs no edit to a deployed
      container.
- [ ] A token with the cross-tenant read permission sees every tenant on GET and history, and
      still gets 404 on PUT and DELETE and 403 on a POST naming another tenant.
- [ ] Every model declares `__tenant_scoped__`; `scripts/common/validate_modules.sh` fails when one
      does not.

### How the tests must be built

The isolation suite **provisions its own tenants, users, tokens and rows, and deletes them**
(`rules/testing-guidelines.md` § "A test owns the data it needs"). This is not style. The first
version of this suite asserted on the *text* of `crud.py`, and its one live check accepted either
200 or 403 — so it stayed green while no user in the installation could reach any data at all.

Two mechanics make a real suite possible:

- **Per-user tokens** come from Authentik's `client_credentials` grant with a *service account's*
  username and an app-password token. It issues a token carrying that user's own attributes, which
  is what makes two tokens with two different tenant claims possible. `TEST_AUTH_TOKEN` cannot: it
  is one identity.
- **Assert against the format the system emits** (`<TenantName>(<id>)`), never a convenient one. A
  suite that tests `[1]` is testing a shape production never produces. Assert on the *shape*, not on
  a name: a tenant name is an editable label and the installation's own, so a suite naming one is
  a suite that passes in exactly one installation.
