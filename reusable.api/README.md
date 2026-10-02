# `reusable.api` — the shared backend framework implementation

The backend half of what `reusable.ui/` is for the frontend: **one implementation of the framework,
at the top level of the repository, consumed by every module's backend including host_app's.**

```
reusable.api/
  ideable_api/
    tenancy.py       TenantScope
    query.py         the generic query core
    entities.py      EntityDescriptor + the per-module registry
    associations.py  AssociationDescriptor + the query side for a module's link tables
    router.py        the generated endpoints
    residue.py       the test-residue cleanup: `python -m ideable_api.residue`
    platform.py      what the framework needs from its host module
```

## What a module does with it

Declare your entities, freeze, mount:

```python
from ideable_api.entities import freeze_registry, mount_entity_routers
from ideable_api.platform import AuditBinding, Platform

from . import audit, auth, database
from .entities import items          # registers itself on import
freeze_registry()

PLATFORM = Platform(
    get_db=database.get_db,
    require_permission=auth.require_permission,
    require_tenant_scope=auth.require_tenant_scope,
    module_slug=os.getenv('MODULE_SLUG', 'template'),
    audit=AuditBinding(
        system_actor_username=audit.SYSTEM_ACTOR_USERNAME,
        unavailable_error=audit.AuditUnavailableError,
        ensure_utc=audit.ensure_utc,
        get_system_startup_at=audit.get_system_startup_at,
        make_synthetic_creation_row=audit.make_synthetic_creation_row,
    ),
)

mount_entity_routers(app, PLATFORM)
```

Every registered entity gets its six endpoints. There is nothing to opt into — what a maintainer
chooses is whether to call them, and whether the frontend uses `@ideable/ui`'s `StandardEntityPage`
or a page of its own. `mount_entity_routers` mounts the module's declared **associations** in the
same call.

## Associations: a link table, declared

An association is a row of a link table addressed by the rows it links — a role's permission, a
profile's role, a user's grant. It is not an entity (no id of its own in the API, its text comes
from the rows it joins, its permission is its own), so it gets its own declaration:

```python
from ideable_api.associations import AssociationDescriptor, register_association

AS_USER_PROFILE = register_association(AssociationDescriptor(
    key='as_user_profile',
    model=UserProfile, left_col='user_fk', right_col='profile_fk',
    left_model=User, right_model=Profile,
    scope_col='tenant_fk', scope_model=Tenant,       # optional THIRD key
    text_fields={'user.username': lambda user, profile: user.username or ''},
    response_fields={'username': 'user.username'},   # the CLEAN name a row carries
    create_schema=..., update_schema=..., read_schema=..., page_schema=Page[AsUserProfile],
    permission_resource='profile_to_user_assignments',
    narrow=lambda db: (lambda row: ...),             # the caller's administration scope
    validate=lambda db, keys: ...,                   # a rule spanning the linked rows
    before_create=..., before_update=..., before_delete=...,
    after_create=..., after_update=..., after_delete=...,
))
```

It gets five endpoints (`GET /<key>`, `GET /<key>/{id}`, `POST`, `PUT`, `DELETE`), the synthetic id
`<left>__<right>[__<scope>]`, and the `{items, total, page, size, pages}` envelope the
`@ideable/ui` association view reads. `narrow` is applied by the query side on both read paths, so
no route can forget it; the hooks are where a module's own rules go, because the framework knows
nothing of any module's authorization model. `AssociationDescriptor` is refused for a link table
declaring `__tenant_scoped__ = True`: the query side applies no tenant predicate, and a declaration
it would serve unscoped must fail the line that builds it. The full contract is
`modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md` § *Associations are
declared, not written*.

## Four declarations instead of hand-written routes

Each is an optional `EntityDescriptor` field; a descriptor that sets none behaves as it always has.

```python
EntityDescriptor(
    ...,
    tenant_from=(Asset, 'asset_fk'),                 # a child's tenant is its parent's, read in the caller's scope
    derived_filters={'risk_aspect': lambda query, value: query.filter(...)},  # a list param that is not a column
    read_permission_resources=('assessment',),       # ALSO opens reads; writes keep permission_resource
    version_schema=AssetVersion, version_page_schema=AssetVersionPage,   # history tracks its model columns
)
```

`/history` carries the columns the `version_schema` declares (those that are columns of the model), not
the filter whitelist. `tenant_from` refuses, with the tenant-scope `403`, a missing parent key, a
parent the caller cannot see, and a payload tenant that disagrees. A derived filter runs after tenant
scoping and can only narrow. The full contract is `modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md`
§ *Four declarations for what a module used to hand-write*.

## Test residue: what a run created is removed

`python -m ideable_api.residue` — run inside a module's backend container — records which rows exist in
every table the module declares as an entity, and later removes the rows that are not in that record. It is
how a test run leaves a module's data as it found it, whoever created the rows and whether or not the spec
that did meant to clean them up.

```
python -m ideable_api.residue --snapshot                 # prints {"<table>": [ids…]} as the LAST line
python -m ideable_api.residue --purge --since -          # the snapshot on stdin; removes what it lacks
python -m ideable_api.residue --purge --since - --dry-run
```

- **The tables are the registry's.** Every entity descriptor's model, read from `app.entities`; the
  module's database session is `app.database.SessionLocal`. Nothing is listed per module, so a remote gets
  the command by sync and covers its own entities.
- **Row-level security is crossed with the mechanisms the policies already offer, not a privileged role.**
  The rows to remove are found with `app.cross_tenant_read = on` (which sees every tenant, including one
  that no longer exists) and deleted with `app.tenant_ids` set to exactly the tenants of those rows.
- **Children first.** Tables are cleaned in the reverse of the model's dependency order. A row a foreign
  key still protects (a table the registry does not know points at it) is **kept and reported**, never
  forced. The version rows (`<table>_version`) of a removed row go with it.
- **The gate fails closed.** It needs `E2E_TEST_USERS_ENABLED=true` AND `IDEABLE_EXECUTION_MODE` given and
  not `prod`. A module's container carries neither, so the runner passes both from the deployed config; an
  absent value refuses and deletes nothing.
- **Reported out loud**: per table, the rows removed and the rows kept with the reason. Exit `0` when the
  purge ran (kept rows are a warning in the report), `1` when it refused or failed.
- **Assumption**: nobody else writes to the stack while the suites run; a row someone else created in that
  window is indistinguishable from a test's.

## A delete the datamodel restricts is a 409

`DELETE /<key>/{id}` of a row another row still points at (a parent with children) does not crash: the core
rolls the transaction back and raises `StillReferenced` (`entities.py`), and the generated route answers
**`409 Conflict`** with `<key> is still referenced by <table> and cannot be deleted`. Only PostgreSQL's
foreign-key violation (SQLSTATE `23503`) is converted; any other database failure stays the server error it
was. `StillReferenced` is a plain exception, not an `HTTPException`, because only `router.py` imports
fastapi — a module's hand-written delete that calls `delete_entity_row` maps it the same way. The schema is
never changed to avoid it: the datamodel restricts the delete on purpose, and a cascade would turn "refuse"
into "silently erase the children and their history".

## A read-only entity

`EntityDescriptor.read_only = True` mounts only the three read routes (list, get-one, describe) —
POST/PUT/DELETE are not mounted at all, not mounted-and-refusing. For an entity whose rows may
only ever be written by something other than this API (host_app's `permissions`, populated solely
from each module's `authorization.yaml` catalog), that is the honest shape: a write route a caller
could find and always get refused is worse than no route to find.

`create_schema`/`update_schema` are still required on the descriptor even when `read_only` is
set — they cost nothing unused, and the alternative (making them optional) would give the
descriptor a second shape for what one flag already says.

## A module with no tenancy, or a mix

`require_tenant_scope` is the one `Platform` field that may be omitted. `TenantScope` cannot
represent "no tenants" — it requires at least one, by design — so a module whose data is not
partitioned by tenant has no answer to give and none is asked of it.

What decides whether a GIVEN entity needs one is **that entity's own `__tenant_scoped__`**, never
the module's. A module may declare some entities tenant-scoped and others global at once — the
read filter (`scoped_to_readable_tenants`) already worked this way; the write path and the
router's dependency now match it. Mounting a tenant-scoped entity with `require_tenant_scope`
unset is a startup error (`RuntimeError` from `build_entity_router`), not a request that runs
unscoped — the mismatch surfaces once, at deploy, rather than on whichever request happens to hit
the missing check first.

## How it reaches a backend

Two mechanisms, both mirroring how `reusable.ui` reaches a frontend:

| | |
|---|---|
| **in a clone** | `<module>/backend/SOURCES/.ideable-api` — a tracked relative symlink to this folder, on `PYTHONPATH` |
| **in an image** | `--build-context ideable_api=<repo>/reusable.api`, and `COPY --from=ideable_api` in the Dockerfile |

The second is not a convenience: Docker does not follow a symlink out of the build context, so a
symlink alone gives a working developer machine and an image that cannot import the package.

Both are set up by each backend's `SPECS/build.sh`.

## Changing it

This is **framework-owned**. In a remote module project it arrives by template sync and local edits
are overwritten; a change belongs in the Ideable repository. Two rules for a change made here:

1. **No import of a module's `app` package, ever.** What the framework needs from its host goes
   through `Platform`. `scripts/TESTS/test_the_backend_framework_is_shared.py` enforces this.
2. **It runs in every module's backend.** A behaviour only one module wants is that module's code,
   not a flag here.
