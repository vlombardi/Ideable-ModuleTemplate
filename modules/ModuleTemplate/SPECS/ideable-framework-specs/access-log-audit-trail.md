> **Status: Design Reference / Future Exploration**
> This document describes a potential standalone Audit Service architecture for access-log audit
> trail functionality. It is **NOT** part of the current implementation spec chain and does **NOT**
> override the active access-log model defined in `HostApp/backend/SPECS/base_specs.md`.
> Do not implement from this document without explicit promotion into the spec chain.
> A dedicated Access Log Audit Trail refactoring will evaluate and formalise this design.

---

# Specification Prompt: Authentik Audit Trail with OIDC Back-Channel Logout

## Context and Goal

You are building a **production-grade audit trail system** for a web application that uses **authentik 2025.10.x** as its Identity Provider (IdP) via OpenID Connect (OIDC). The audit trail must record security-relevant session and identity events with consistent session correlation, minimal polling, and no dependency on browser-mediated flows.

The system must be implemented as a backend service (the "Audit Service") that:
- Receives push notifications from authentik via **OIDC Back-Channel Logout** and **Webhook Notification Rules**
- Exposes its own internal API for querying the audit log
- Persists all events in a relational database
- Correlates all events belonging to the same session using a consistent `session_id`

---

## Authentik Configuration Requirements

### 1. OIDC Provider Setup
- Configure an OAuth2/OIDC provider in authentik with **Back-Channel Logout** enabled
- Set the **Back-Channel Logout URI** to `https://<audit-service>/backchannel-logout`
- Ensure the provider emits a `sid` claim in the **ID token** at login time
- The `sid` claim must be a stable UUID that identifies the authentik `AuthenticatedSession` for the duration of its lifecycle

### 2. Notification Rules (Webhook Transport)
Configure **separate Notification Rules** in authentik (Admin UI → Events → Notification Rules) for each of the following event actions, all pointing to a webhook transport at `https://<audit-service>/webhooks/authentik`:

| Event Action | Trigger Condition |
|---|---|
| `login` | Any |
| `login_failed` | Any |
| `authorize_application` | Any |
| `suspicious_request` | Any |
| `impersonation_started` | Any |
| `impersonation_ended` | Any |
| `password_set` | Any |

> **Note:** `logout` events are handled exclusively via Back-Channel Logout, not via webhook, to ensure the `sid` claim is available at logout time.

### 3. Authentik API Token
- Create a dedicated **Service Account** in authentik with read-only access to:
  - `GET /api/v3/core/authenticated_sessions/`
  - `GET /api/v3/events/events/`
- Store the token securely as an environment variable in the Audit Service (`AUTHENTIK_API_TOKEN`)

---

## Events to Track and Their Data Model

For each event, the Audit Service must persist the following fields.

### Common fields (all events)

| Field | Source | Notes |
|---|---|---|
| `id` | Generated (UUID v4) | Internal audit record ID |
| `session_id` | See per-event notes | Stable identifier for the authentik session |
| `event_type` | Event action name | e.g. `login`, `login_failed`, `authorize_application` |
| `timestamp` | `created` field from authentik event | ISO 8601 UTC |
| `user_pk` | `user.pk` | authentik user primary key |
| `username` | `user.username` | |
| `user_email` | `user.email` | |
| `client_ip` | `client_ip` | |
| `raw_payload` | Full JSON | Store the complete event payload for forensic use |
| `ingested_at` | Server time at ingestion | For latency tracking |

### Per-event additional fields and session_id resolution

#### `login`
- `auth_method`: from `context.auth_method` (e.g. `password`, `sso`)
- `session_id`: **resolve via authentik API** — after receiving the webhook, call `GET /api/v3/core/authenticated_sessions/?user={user_pk}` and identify the most recently created session. Store its UUID as `session_id`. Cache the mapping `user_pk → session_id` internally.
- If multiple concurrent sessions exist for the same user, disambiguate using `client_ip` match.

#### `login_failed`
- `failed_username`: from `context.username` (may differ from the authenticated user)
- `failed_stage`: from `context.stage.name`
- `session_id`: **null** — no session is created for failed logins. Record as `NULL` in the DB.

#### `logout` (via Back-Channel Logout JWT)
- `session_id`: extracted directly from the `sid` claim of the **logout token JWT**
- Validate the JWT signature against authentik's JWKS endpoint (`/application/o/<app>/jwks/`) before processing
- Look up the existing session record by `session_id` and mark it as closed

#### `authorize_application`
- `application_name`: from `context.authorized_application.name`
- `application_pk`: from `context.authorized_application.pk`
- `scopes`: from `context.scopes`
- `session_id`: use the cached `user_pk → session_id` mapping established at login time

#### `suspicious_request`
- `reason`: from `context` free-form description (revoked token, etc.)
- `session_id`: attempt lookup via `user_pk → session_id` cache; if not found, set to `NULL`

#### `impersonation_started`
- `impersonator_pk`: from `user.pk` (the admin who initiated impersonation)
- `impersonated_pk`: from `context.as_user.pk`
- `impersonated_username`: from `context.as_user.username`
- `session_id`: use cache for the impersonator's `user_pk`

#### `impersonation_ended`
- Same fields as `impersonation_started`
- Correlate start/end pairs by `impersonator_pk` + timestamp proximity

#### `password_set`
- `session_id`: use cache for `user_pk`
- Flag whether this is a self-service reset or an admin-initiated change (check if `user.pk == context.user.pk`)

---

## Session Lifecycle State Machine

Maintain a `sessions` table in the Audit Service DB with the following lifecycle states:

```
OPEN → CLOSED (via logout back-channel)
OPEN → EXPIRED (inferred, see below)
```

| State | Trigger |
|---|---|
| `OPEN` | `login` event received and `session_id` resolved |
| `CLOSED` | Back-channel logout JWT received with matching `sid` |
| `EXPIRED` | Session absent from `/api/v3/core/authenticated_sessions/` but no logout event received |

**Session expiry inference**: Run a background job every 15 minutes that calls `GET /api/v3/core/authenticated_sessions/` for each user with an `OPEN` session in the local DB. If the session UUID is no longer present, mark it as `EXPIRED` with `expired_at = now()`. This is a best-effort timestamp, not an exact one — document this limitation in the audit log UI.

---

## Back-Channel Logout Endpoint Specification

`POST /backchannel-logout`
- Content-Type: `application/x-www-form-urlencoded`
- Body parameter: `logout_token`

**Validation steps** (mandatory, in order):
1. Parse the JWT header — reject if `alg` is `none`
2. Fetch authentik's JWKS from `https://<authentik-host>/application/o/<app>/jwks/` (cache with 1-hour TTL)
3. Verify JWT signature against JWKS
4. Verify `iss` claim matches the authentik issuer URL
5. Verify `aud` claim matches this application's client ID
6. Verify the token contains `"events": {"http://schemas.openid.net/event/backchannel-logout": {}}` — reject if absent
7. Verify `iat` is not more than 5 minutes in the past — reject stale tokens
8. Extract `sub` (user identifier) and `sid` (session identifier)
9. Look up the session by `sid` in local DB and transition to `CLOSED`

**Response codes:**
- `200 OK` — token validated and session closed
- `400 Bad Request` — malformed token
- `501 Not Implemented` — if `sid` is absent (should not occur with this setup)

---

## Webhook Ingestion Endpoint Specification

`POST /webhooks/authentik`
- Content-Type: `application/json`
- Authentication: shared secret via `Authorization: Bearer <WEBHOOK_SECRET>` header (configure this in the authentik Notification Transport)

**Processing pipeline:**
1. Validate the `Authorization` header — reject with `401` if invalid
2. Parse the JSON body
3. Extract `action`, `user`, `context`, `client_ip`, `created`
4. Route to the appropriate handler function based on `action`
5. Resolve `session_id` using the cache or API call (see per-event rules above)
6. Persist to the `audit_events` table
7. Respond `200 OK` synchronously — all heavy processing (API calls) must be done asynchronously in a background task to avoid webhook timeout

---

## Database Schema (Minimum)

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,                  -- authentik session UUID (= sid)
    user_pk INTEGER NOT NULL,
    username TEXT NOT NULL,
    user_email TEXT,
    client_ip TEXT,
    state TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | CLOSED | EXPIRED
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    expired_at TIMESTAMPTZ
);

CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id),  -- NULL allowed for login_failed
    event_type TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    user_pk INTEGER,
    username TEXT,
    user_email TEXT,
    client_ip TEXT,
    extra JSONB,                              -- per-event additional fields
    raw_payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON audit_events (session_id);
CREATE INDEX ON audit_events (user_pk, timestamp DESC);
CREATE INDEX ON audit_events (event_type, timestamp DESC);
```

---

## Security Requirements

- **Webhook secret rotation**: support hot rotation via environment variable without restart
- **JWKS caching**: cache the JWKS response with a 1-hour TTL; force-refresh on signature verification failure before rejecting a token
- **No raw passwords in logs**: authentik already redacts passwords (`********************`) in `login_failed` events, but assert this in the ingestion pipeline
- **Admin impersonation flag**: any `audit_event` with `event_type = impersonation_started/ended` must be surfaced with a high-visibility flag in any UI consuming this data
- **Idempotency**: use the authentik event `pk` field as a deduplication key — reject duplicate ingestions gracefully with `200 OK`
- **Sensitive field masking**: mask `user_email` in query responses to non-admin consumers (show only first 2 chars + `***@domain`)

---

## Known Limitations to Document

1. **`session_id` for non-logout events** is resolved heuristically via the authenticated_sessions API, not from the event itself. In rare cases of concurrent sessions from the same IP, the mapping may be ambiguous.
2. **`session_expired` events do not exist** natively in authentik. The `EXPIRED` state is inferred by polling and carries a timestamp precision of ±15 minutes.
3. **Token refresh is not tracked** at the event level. Refresh activity can only be inferred from the presence of an active session over time.
4. **Back-channel logout is not triggered** by admin-forced session invalidation via the authentik Admin UI in some versions — verify behavior on your specific authentik version and test explicitly.
5. **OIDC RP-Initiated Logout** (`/application/o/<app>/end-session/`) may not always generate a back-channel logout notification depending on client configuration — use the standard invalidation flow (`/api/v3/flows/executor/default-invalidation-flow/`) as the canonical logout path.