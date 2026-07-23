# Ideable Framework — Audit Trail Specification

This file is the authoritative cross-cutting contract for audit trail functionality in all
Ideable modules (host_app and remote modules derived from module_template). It covers backend
versioning, history endpoint shape, association tracking, and frontend rendering.

Backend implementors must read the relevant sub-module `base-specs.md` for build/auth/API
context, then this file for the full audit trail contract.

Frontend implementors must read `shared-ui-specs.md` and `shared-ui-widgets-specs.md` for
widget-level behaviour, then this file for audit-trail-specific rendering rules.

---

## 1. Scope

The audit trail tracks **field-level changes** and **association-level changes** on versioned
entities so that any authorised user can answer "what changed, when, and by whom" for any
given entity record.

It is distinct from the **Access Log**, which is a session-level and system-wide observability
surface (logins, logouts, application authorisations). See `access-log-audit-trail.md` for the
Access Log design reference.

---

## 2. Backend Contract

### 2.1 Entity versioning

Every main entity model must opt in to SQLAlchemy-Continuum versioning by setting
`__versioned__ = {}` on the declarative base model:

```python
from .database import Base

class TemplateItem(Base):
    __tablename__ = 'template_items'
    __versioned__ = {}
    ...
```

To explicitly exclude a model from versioning:

```python
class SomeTransientModel(Base):
    __versioned__ = {'exclude': True}
    ...
```

SQLAlchemy-Continuum auto-generates `<table>_version` and `transaction` tables at startup via
`Base.metadata.create_all()`. These tables must not be defined manually in `datamodel.sql`.
For production, use Alembic to manage version table migrations.

### 2.2 Association versioning

M2M join tables and single-owner FK association tables that link versioned entities must also
set `__versioned__ = {}` so that add/remove operations on associations are captured alongside
field-level changes:

```python
class UserProfile(Base):
    __tablename__ = 'as_user_profile'
    __versioned__ = {}
    user_fk = Column(Integer, ForeignKey('users.id'))
    profile_fk = Column(Integer, ForeignKey('profiles.id'))
```

Association tables that are purely transient or carry no auditable semantic (e.g. session
scratch tables) may opt out via `__versioned__ = {'exclude': True}`.

### 2.2bis No inline `au_*` columns on entity tables

**Rule**: Business tables in `datamodel.sql` must contain **only business fields and foreign keys**.  They must **NOT** contain `au_creation_timestamp`, `au_last_update_timestamp`, `au_created_by_user`, or `au_last_updated_by_user`.

**Rationale**: SQLAlchemy-Continuum stores creation timestamp, update timestamp, and actor in its generated `<table>_version` and `transaction` tables.  Inline audit columns on the base table would require manual population in every CRUD path, introduce drift risk when code paths forget to set them (e.g. bulk operations, raw SQL, or background tasks), and duplicate metadata that Continuum already captures reliably.

**Correct pattern**: `__versioned__ = {}` on the ORM model is sufficient.  History endpoints read from Continuum version tables via `version_class(Model)` and the `transaction` / `transaction_meta` tables.

### 2.3 History endpoint pattern

Every versioned entity must expose a single read-only history endpoint that returns **both**
field-change events and association-change events, merged, sorted, and **paginated**:

```
GET /<entity>/{entity_id}/history?skip={skip}&limit={limit}&sort_by={sort_by}&sort_order={sort_order}
```

Query parameters:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `skip` | integer | `0` | Number of history rows to skip |
| `limit` | integer | `50` | Maximum number of history rows to return |
| `sort_by` | string | `timestamp` | Column to sort by (`timestamp`, `actor`, `operation_type`) |
| `sort_order` | string | `desc` | Sort direction (`asc` or `desc`) |

**Response shape** (`Page[*Version]`):

```json
{
  "items": [ /* array of version rows */ ],
  "total": 42,
  "page": 1,
  "size": 50,
  "pages": 1
}
```

Permission guard: `require_permission('<module_slug>.audit_trail:view')`.
The backend must return `403` when the claim is absent and `401` for missing/invalid tokens.

> **Permission model reminder**: permissions are stored as bare `<resource>:<action>` strings
> inside the per-module JWT array (`<module_slug>.permissions`). At runtime the backend builds a
> single flat set by prepending each entry with the module slug. `require_permission()` always
> receives the fully-qualified `<module_slug>.<resource>:<action>` form. Never pass a bare
> `<resource>:<action>` string to `require_permission()`.

#### Field-change row shape

| Field | Description |
|---|---|
| `operation_type` | `0` = `INSERT`, `1` = `UPDATE`, `2` = `DELETE` (SQLAlchemy-Continuum integer constants) |
| `actor` | authenticated username (never a display name, email, or numeric ID) |
| `actor_id` | user ID of the actor (for parenthesized display in the UI) |
| `timestamp` | ISO 8601 UTC — for Continuum-backed entities, sourced from the `transaction.issued_at` column (not the model's `au_creation_timestamp`) |
| `<field>` | all business field values at that version |

#### Association-change row shape

| Field | Description |
|---|---|
| `operation_type` | `3` = `ASSOCIATE` (INSERT on join table) or `4` = `DISASSOCIATE` (DELETE on join table) |
| `association_name` | join table name or human-readable label (e.g. `"user_profile"`) |
| `peer_entity_type` | type of the associated peer (e.g. `"profile"`) |
| `peer_entity_id` | peer primary key |
| `peer_entity_label` | human-readable identifier for the peer (e.g. name, username) |
| `actor` | authenticated username |
| `actor_id` | user ID of the actor |
| `timestamp` | ISO 8601 UTC — for Continuum-backed entities, sourced from the `transaction.issued_at` column |

**Timestamp sourcing rule**: The `timestamp` field must reflect the wall-clock time when the audited event occurred. For Continuum-backed entities this is the transaction commit timestamp (`transaction.issued_at`), NOT the entity's `au_creation_timestamp` (which represents the original row creation time). Synthetic creation rows (§2.4) are the exception: they use the module startup timestamp.

The `operation_type` field is the discriminator between the two row kinds. Both kinds must
appear in the same response list, sorted by `timestamp` descending (most recent first).
Synthetic creation rows are the only exception — they use the module/server startup timestamp
(§2.4) and sort to the bottom of the list.

### 2.4 Creation guarantee

Every audited entity MUST have at least one history row that represents its creation.
If the underlying audit source does not provide a creation event, the backend MUST synthesize
one using the module/server startup timestamp as the creation time and `"system"` as the actor.

### 2.5 Actor injection

Every request that modifies a tracked entity or its associations must record the authenticated
username as the actor.  The canonical mechanism is a **global generator dependency** attached
to the FastAPI app so the actor is set automatically for every authenticated request and
always cleared afterward:

```python
# app/main.py
from fastapi import FastAPI, Depends
from .auth import _get_current_username_optional
from .audit import set_current_user, clear_current_user


async def _audit_actor_dependency(
    username: str | None = Depends(_get_current_username_optional),
):
    """Must be an async generator so FastAPI runs it in the same asyncio
    task as the route handler; sync generators execute in a thread pool and
    the ContextVar set there does not propagate to the handler."""
    if username:
        set_current_user(username)
    yield
    clear_current_user()


app = FastAPI(
    ...,
    dependencies=[Depends(_audit_actor_dependency)],
)
```

Generator dependencies execute the code before `yield`, run the route handler, then execute
the code after `yield`.  This guarantees the actor is set in the handler's execution context
and is always cleared afterward, regardless of exceptions.

`_get_current_username_optional` must be implemented in `app/auth.py` as a dependency that
reuses the same JWT validation path as the auth stack, accepts both the `Authorization`
header and the `oauth2_token` from `OAuth2AuthorizationCodeBearer`, and returns `None` for
unauthenticated or invalid requests instead of raising. This makes the global dependency
safe for public routes such as `/health`.

Per-route `set_current_user()` calls are **not allowed**. The global dependency is the
only mechanism for actor injection and must be present in every module's `main.py`.

The actor must be the authenticated username from the validated JWT. Using a display name,
email address, or numeric ID as the actor is not allowed.

### 2.6 Reusable history factories (mandatory)

Every module must use the factory utilities exported by `app/audit.py` to build history responses.
These factories guarantee consistent timestamp handling, actor normalization, and UTC coercion
across all entities.

#### `build_transaction_map(db, version_rows)`

Builds a `transaction_id → issued_at` mapping from SQLAlchemy-Continuum's `transaction` table.
Rolls back the session on SQLAlchemyError. Returns an empty dict when there are no version rows.

```python
tx_map = build_transaction_map(db, versions)
```

#### `make_synthetic_creation_row(schema_cls, entity, startup_at=None, **overrides)`

Creates a synthetic INSERT row when an entity has no version history. Uses the module startup
timestamp and `"system"` as the actor. Business fields are copied from `entity` unless overridden.

```python
if not versions:
    return [make_synthetic_creation_row(
        schemas.TemplateItemVersion, item, startup_at,
        name=item.name,
        description=item.description,
    )]
```

#### `version_row_to_schema(version_row, schema_cls, tx_map, startup_at=None, **overrides)`

Converts a single Continuum version ORM row into a Pydantic schema instance. Resolves timestamps
from `tx_map`, forces UTC via `ensure_utc`, normalises the actor, and copies all non-callable
attributes from the ORM row.

```python
field_versions = [
    version_row_to_schema(v, schemas.TemplateItemVersion, tx_map, startup_at)
    for v in versions
]
```

#### `merge_and_sort_history(field_versions, association_rows, startup_at=None)`

Merges field-change and association-change rows into a single list sorted by `timestamp` descending
(most recent first).

```python
return merge_and_sort_history(field_versions, association_rows, startup_at)
```

#### `BaseVersion` schema base class

Every entity-specific `*Version` Pydantic schema must inherit from `BaseVersion` (defined in
`app/schemas.py`). This guarantees a uniform shape for audit metadata and association-change
fields across all modules:

```python
class BaseVersion(BaseModel):
    transaction_id: int
    operation_type: int
    end_transaction_id: Optional[int] = None
    id: Optional[int] = None
    association_name: Optional[str] = None
    peer_entity_type: Optional[str] = None
    peer_entity_id: Optional[str] = None
    peer_entity_label: Optional[str] = None
    timestamp: Optional[datetime] = None
    actor: Optional[str] = None
    actor_id: Optional[int] = None
```

Entity-specific schemas only add business fields:

```python
class TemplateItemVersion(BaseVersion):
    name: Optional[str] = None
    description: Optional[str] = None
```

> **Rule**: Do not inline the common audit fields into each entity schema. Always inherit from
> `BaseVersion` so that the frontend `AuditTrailPopup` and all history endpoints share the same
> contract. The `actor` field maps to the authenticated username; `actor_id` maps to the
> numeric user ID (may be `None` for synthetic rows). `timestamp` is the wall-clock event time.

### 2.7 Authentik-backed entities (event-sourced)

For entities that live in Authentik (not a local DB), the audit trail is built from the
Authentik event log rather than SQLAlchemy-Continuum. History rows must conform to the same
field-change row shape as DB-backed entities, with these additions:

- Include request metadata when available: `client_ip`, `user_agent`, `request_method`,
  `request_path`.
- Include the event type from Authentik alongside `operation_type`.
- The creation guarantee still applies: synthesize a creation row if Authentik events do not
  include one.

Association changes for Authentik-backed entities (e.g. a role added to a profile) must use
the same `ASSOCIATE`/`DISASSOCIATE` shape defined in §2.3.

---

## 3. Frontend Contract

### 3.1 Audit Trail action

- Every entity page that exposes a history endpoint must include an audit trail action icon
  (`History` from lucide-react) in the table action column.
- The icon is shown only when the current JWT includes `audit_trail:view` in
  `<module_slug>.permissions`.
- Clicking the icon opens the **Audit Trail Popup** (see `shared-ui-widgets-specs.md` for the
  full popup contract).
- The legacy per-page "Show audit data" toggle is not allowed; audit visibility is controlled
  exclusively by the permission-gated action icon.

### 3.2 Popup structure

- The first tab shows the selected entity's own history (field-change and association-change
  rows merged, as returned by the `/history` endpoint).
- If the entity has directly associated entities that also expose history endpoints, the popup
  includes one additional tab per associated entity showing that peer's own field-change history.
- Associated-entity tabs show that peer entity's field-change history only; association-change
  events belong to the parent entity's tab, not the peer's tab.

### 3.3 Audit table columns and features

Every audit trail table must use server-side data fetching. This means it **must** support:

- **Server-side pagination** — `skip`/`limit` query parameters with standard pagination
  controls (First `«`, Previous `‹`, page X of Y, Next `›`, Last `»`). The total row
  count comes from the `total` field of the paginated response.
- **Column sorting** — every column header must be clickable to sort ascending or descending,
  with visual indicators (`↕`, `↑`, `↓`). Sort parameters are forwarded to the backend.

**Component contract**: `AuditTrailPopup` accepts per-tab `fetchPage` callbacks:

```typescript
interface AuditPageParams {
  skip: number
  limit: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

interface AuditTab {
  label: string
  columns: string[]
  fetchPage: (params: AuditPageParams) => Promise<VersionPage>
}
```

The popup component calls `fetchPage` whenever pagination or sort state changes. Callers
(entity pages) supply the callback, wiring it to the appropriate history endpoint via the
entity service.

The audit table must present exactly **four** columns, in this order:

| Column | Header | Content |
|---|---|---|
| **When** | `When` | The event timestamp (`timestamp`), rendered as a locale-aware datetime string. |
| **Who** | `Who` | The actor rendered as `username(user_id)` — e.g. `john_doe(42)`. If the user ID is unavailable, render `username` alone. |
| **Op** | `Op` | The operation type rendered as a compact label/badge: `INSERT`, `UPDATE`, `DELETE`, `ASSOCIATE`, `DISASSOCIATE`. Association rows (`ASSOCIATE`/`DISASSOCIATE`) must include the `Link`/`Unlink` icon from lucide-react. |
| **What** | `What` | The detail of the change. For field-change rows: a diff of changed field values (`Field: old → new`). For association rows: `association_name`, `peer_entity_type`, and `peer_entity_label`. For INSERT with no previous row: all populated field values. For DELETE: the word `Deleted`. |

> **Rule**: The audit table must not render inline `au_*` metadata columns (e.g. `Created At`,
> `Updated At`, `Creator`, `Updater`) as separate columns. That metadata is already folded into
> the **When** and **Who** columns.

### 3.4 Row rendering

Field-change rows and association-change rows must remain visually distinct inside the
**What** column:

- **Field-change rows** (`operation_type` `0`/`1`/`2`): render as a diff of changed field
  values. On INSERT with no previous version, list all populated business fields.
  On DELETE, show `Deleted`.
- **Association-change rows** (`operation_type` `3`/`4`): render with a distinct icon
  (`Link` for `ASSOCIATE`, `Unlink` for `DISASSOCIATE` from lucide-react) inside the **Op**
  column, and display `association_name`, `peer_entity_type`, and `peer_entity_label` inside
  the **What** column.

Both row kinds supply the same **When** and **Who** values.

### 3.5 General rendering rules

- Audit tables must follow the shared column-formatting conventions for audit metadata.
- Backend history endpoints return `401` for invalid tokens and `403` when `audit_trail:view`
  is absent; the popup must surface these error states rather than silently failing.
- Every audited entity must have at least one history row; the popup must never render an
  empty history tab.
