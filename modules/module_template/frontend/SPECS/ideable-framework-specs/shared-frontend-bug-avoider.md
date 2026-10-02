# Shared Frontend Bug Avoider — Framework-Level Rules

These rules apply to every module's frontend. Module-specific `general_bug_avoider.md` files reference this file; do not duplicate these entries there.

---

## Audit Trail Popup: raw version tables are not useful

**Bug**: `AuditTrailPopup` displayed a raw table of all version fields (transaction_id, every column value). Users could not tell what changed between versions, and the table was too wide and hard to read.

**Fix**: Redesign the popup to show a focused timeline with four columns: **Op**, **When**, **Who**, **What Changed**. Compute per-field differences:
- **INSERT** → lists all initial non-empty field values
- **UPDATE** → shows only changed fields as `Field: old → new`
- **DELETE** → shows "Deleted"
- Updates with no visible changes → shows "No visible changes"

**Rule**: Audit trail popups must never dump raw version rows. They must compute and display field-level diffs so users can immediately see what changed. Skip internal metadata keys (`transaction_id`, `operation_type`, `end_transaction_id`, `au_*`, `event`, `client_ip`, `user_agent`, `request_method`, `request_path`) from diff computation.

---

## Entity pages: edit/delete action icons must be hidden in view mode

**Bug**: Entity pages showed edit and delete icons in the actions column even when `isEditEnabled` was `false` (view mode). Users could click them, though the underlying operations were still permission-gated.

**Fix**: Render row actions with the shared `RowActions` / `RowActionButton` widgets from
`@ideable/ui`, and wrap the mutating ones with `isEditEnabled &&`:
```tsx
import { RowActions, RowActionButton } from '@ideable/ui'  // host_app: '@/components/RowActionButton'
import { History, Pencil, Trash2 } from 'lucide-react'
// ...
cell: ({ row }) => (
  <RowActions onClick={(e) => e.stopPropagation()}>
    {canViewAuditTrail && (
      <RowActionButton icon={History} title={t('table.viewAuditTrail')} aria-label={t('table.viewAuditTrail')} onClick={...} />
    )}
    {isEditEnabled && canUpdate && (
      <RowActionButton icon={Pencil} title={t('common.edit')} aria-label={t('common.edit')} onClick={...} />
    )}
    {isEditEnabled && canDelete && (
      <RowActionButton icon={Trash2} variant="danger" title={t('common.delete')} aria-label={t('common.delete')} onClick={...} />
    )}
  </RowActions>
)
```

**Rules**:
1. **Uniform rendering (normative)**: every entity-table and association-table row-action
   icon MUST be a `RowActionButton` inside a `RowActions` container. Do **not** hand-roll
   `<Button variant="ghost">`/`<button>` with per-module classes in the `actions` column —
   that is what made host_app and remote tables diverge (ghost icons vs bordered squares).
   `RowActionButton` is the single source of truth for the look (rounded-square, bordered,
   hover-accent; `variant="danger"` for destructive delete/unlink). Pass the icon as a
   component via `icon={Icon}` (typed `React.ElementType`, so any lucide install or inline
   SVG works — no cast) and always give a `title` + `aria-label`.
2. **View/edit gating**: all mutating action icons (edit, delete, unlink) must be rendered
   only when `isEditEnabled` is `true`. Do not rely solely on permission checks; the mode
   toggle is an explicit UX contract.

---

## Entity pages without audit trail must not show `au_*` columns

**Bug**: Some entity pages displayed `au_creation_timestamp`, `au_last_update_timestamp`, `au_created_by_user`, and `au_last_updated_by_user` columns even though the entity was static or externally managed and had no meaningful per-object audit trail data. These columns were always empty or misleading.

**Fix**: Remove all `au_*` column definitions from the affected table and remove the audit fields from the detail view panel.

**Rule**: Do not display `au_*` audit columns for entities that are not versioned or do not have a meaningful per-object audit trail. If an entity is static, externally managed, or otherwise lacks audit data, omit the audit fields from both table columns and detail views.

---

## Audit Trail Frontend: `computeDiffs` must skip synthetic association rows when finding `previous`

**Bug**: The audit popup rendered both Continuum field-change rows and synthetic association rows (`ASSOCIATE`/`DISASSOCIATE`) in the same list. `computeDiffs` took `previous = versions[idx + 1]`, which could be a synthetic row containing only association metadata. When comparing a real UPDATE version against a sparse synthetic row, every user field appeared different (the synthetic row had `undefined` for most fields), producing a phantom "all user data changed" diff.

**Fix**: Before calling `computeDiffs`, walk forward from `idx + 1` to find the nearest row whose `operation_type` is NOT `3` (`ASSOCIATE`) or `4` (`DISASSOCIATE`), and use that as `previous`.

**Rule**: When computing field-level diffs in an audit popup that mixes field-change rows with synthetic association rows, always locate the nearest actual field-version row as the comparison baseline. Never compare a Continuum version against a synthetic sparse row.

---

## Audit Trail Popup: must be centered, draggable, and resizable

**Bug**: The Audit Trail Popup was rendered using the Radix `Dialog` component or a custom fixed-position div that appeared offset to the right-bottom of the viewport instead of centered. The popup could not be dragged or resized, making it difficult to view large audit tables.

**Fix**: Replace all audit trail popup implementations with the shared `DraggableResizablePopup` component (`src/components/DraggableResizablePopup.tsx`). This component:
- Centers the popup in the viewport on open
- Provides a drag handle in the header for repositioning
- Provides a resize handle in the bottom-right corner for size adjustment
- Renders via `createPortal` into `document.body` to avoid clipping

**Rule**: Audit trail popups must never use Radix `Dialog` or custom fixed-position divs. They must always use `DraggableResizablePopup` to ensure consistent centering, drag, and resize behavior across host_app and all remote modules.

---

## Serving port: nginx-unprivileged binds 8080, and FIVE files must agree

**Bug**: the frontends moved from nginx to `nginx-unprivileged` (uid 101, cannot bind a privileged port) and the port moved to **8080** in the Dockerfile, `nginx.conf` and the compose healthcheck — but `FRONTEND_PUBLISH` still published `3000:80` and Traefik still routed to `http://frontend:80`. Both containers reported **healthy** and every request was a 502.

The healthcheck could not catch it: it probes the port nginx *binds*. It answers "is nginx up?", never "is anyone pointed at it?".

**Fix**: the port appears in five places and they must all match — `nginx.conf`'s `listen`, the Dockerfile's `EXPOSE`, the compose healthcheck, the container side of `*_FRONTEND_PUBLISH`, and Traefik's upstream URL.

**Rule**: never change the serving port in fewer than all five. `TestFrontendPortAgreesEverywhere` compares them to each other and fails on a partial move. And note where Traefik's config actually comes from — see the next entry.

---

## Traefik config: `traefik/SOURCES/dynamic.yml.template` is GENERATED

**Bug**: the frontend upstream port was edited in `traefik/SOURCES/dynamic.yml.template` twice and reverted twice, with no error and nothing in the diff. `build_and_deploy.py` **generates** that file on every deploy and overwrites both it and the deployed copy.

**Rule**: never hand-edit `traefik/SOURCES/dynamic.yml.template` or `deployment_root/modules/host_app/traefik/dynamic.yml.template`. The source of truth is the generator in `scripts/dev/common/build_and_deploy.py` (the frontend container port is the `FRONTEND_CONTAINER_PORT` constant there). A file that looks like a source and is regenerated is worth checking for before editing anything under `SOURCES/`.

---

## nginx: a second `location` block for the same path refuses to start

**Bug**: adding `location = /env-config.js` while one already existed produced `nginx: [emerg] duplicate location "/env-config.js"` and a crash loop.

**Rule**: modify the existing block, do not add a parallel one. Validate before deploying — it costs seconds:
```bash
docker run --rm --entrypoint nginx -v "$PWD/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginxinc/nginx-unprivileged:alpine -t
```

---

## Dependencies: never rewrite the `@ideable/ui` `file:` path, and never delete the lockfile

**Bug**: the Dockerfile used to rewrite `@ideable/ui`'s `file:` path at build time and then `rm -f package-lock.json`, because the rewrite desynchronised `package.json` from the lock. Every image build therefore re-resolved the whole dependency tree from the registry: an image tagged `<commit>` could not be rebuilt from `<commit>`, and one deploy failed on a transitive version that had resolved fine minutes earlier.

The depth of the path is what forced this. **npm normalises `file:` specifiers when it writes the lock**, so `file:../../../../reusable.ui` becomes `file:../reusable.ui` inside the image (POSIX clamps `..` at the root) and stays depth-4 on the host — two lockfiles that can never match, so `npm ci` refuses.

**Fix**: `package.json` declares `"@ideable/ui": "file:./.ideable-ui"` permanently — `.` has no depth to normalise away, and both sides record `file:.ideable-ui` byte-identically. A developer's clone reaches the library through `SOURCES/.ideable-ui`, a **tracked symlink** to the repo-root `reusable.ui`; the Dockerfile creates the real directory from the `ideable_ui` build context.

**Rules**:
- Never `sed` a dependency spec in a Dockerfile, and never delete `package-lock.json`. Install with `npm ci --install-links --legacy-peer-deps`.
- An `npm` lifecycle hook cannot replace the symlink: npm resolves `file:` dependencies **before** running `preinstall`, so the hook never fires (verified — `ENOENT` on `.ideable-ui/package.json`).
- `.ideable-ui` must stay in `.dockerignore`: inside a SOURCES-rooted context a symlink four levels above the root is dangling.
- Copy it with `cp -R`, never `cp -r` — on BSD/macOS `-r` **follows** symlinks and would replace the link with a full copy of the shared library in every remote module.
- Bump a dependency deliberately (`npm install <pkg>@<ver> --install-links --legacy-peer-deps`) and commit the lock diff. See `modules/host_app/SPECS/dependencies.md`.

**`--install-links` copies, so an installed tree that PERSISTS holds a snapshot of the library, not the library.** On a developer's host npm symlinks the same `file:` dependency and the checkout is live; inside the dev tools container `frontend/SOURCES/node_modules` is a host-cache directory that survives between runs, and the copy in it outlives every later change to `reusable.ui/`. Measured: an export added to the shared hook type-checked on the host and failed in the container with *"Module '@ideable/ui' has no exported member"*, against a snapshot twelve days old — and the quieter half was the UI suite, whose dev server had been building pages against the stale widgets and reporting them green. `run_enabled_tests.sh` now reinstalls when any file under `reusable.ui/` is newer than the installed snapshot (`_shared_ui_snapshot_is_stale`, checked by `scripts/TESTS/test_the_shared_widget_library_is_not_installed_stale.py`). **If you resolve `@ideable/ui` from any other long-lived tree, refresh it the same way** — a stale copy does not announce itself, it answers.

---

## Remote module auth: address the host's token entry exactly, and never call a failure a denial

**Bug**: a fully authorized `sadmin` opening a remote module's Items page was told "You are not authorized to view this page." Two independent defects in series, each of which made the other invisible.

*The wrong token.* `services/authToken.ts` built the sessionStorage key by stripping the authority's trailing slash, while oidc-client-ts writes `oidc.user:${authority}:${client_id}` with the authority **verbatim** — and the documented Authentik authority ends in `/`. The direct lookup therefore matched in no deployment at all. Every call fell through to a fallback scan that returned the **first** `oidc.user:` entry `sessionStorage` yielded, with no check of authority, client or expiry. A leftover entry from an earlier session handed host_app a token whose signing key Authentik no longer published, and host_app answered `401 JWT signing key not found`.

*The wrong message.* `services/permissions.ts` collapsed every failure — no token, 401, 503, network error — into an empty set. The page read the empty set as a denial. So an invalid session, an unreachable authorization service and a genuine lack of permission all rendered the same sentence, and the one thing the user could act on (sign in again) was the one thing the message did not say.

Neither the backend suites nor the live-stack Playwright specs could see it: the backend was right, and a fresh browser context holds exactly one `oidc.user:` entry, so the scan returned the correct token by luck and the authorization specs went green while the defect was live in the browser.

**Fix**: `authToken.ts` addresses the entry as the library wrote it, trying the authority both with and without its trailing slash; it answers **only** from the current authority+client key when both are known, skips expired entries (`expires_at`), and — when the OIDC config is unavailable and the entry cannot be named — scans but returns a token only if exactly one unexpired candidate exists. `permissions.ts` returns `{ permissions, outcome }` with `outcome` in `ok` / `session-expired` / `unavailable`, and the gated page maps each to its own message — `common.notAuthorized`, `common.sessionExpired`, `common.permissionsUnavailable`. Pinned by `frontend/TESTS/test_oidc_token_source_contract.py`.

**Rules**:
- Build the OIDC storage key exactly as `oidc-client-ts` does — `oidc.user:<authority>:<client_id>`, authority **unmodified**. Never normalise, trim or rewrite the authority for the key. Try both slash forms; a deployment's templating decides which one the variable carries.
- A remote module must never send a token it cannot attribute to the current session. An entry belonging to another authority or client is not a worse answer than no token — it is a wrong one, and it costs a 401 that reads downstream as a denial.
- Treat an entry whose `expires_at` has passed as no entry.
- Where the session cannot be identified, **refuse to guess**: one unexpired candidate is the session; several are ambiguous. Never return the first of several.
- The permission fetch must report **why** it failed, and the UI must say "not authorized" only when host_app actually answered. Fail-closed on the data (hide everything) and precise in the message — these are not in tension.
- `getEnv` throws when a variable is unset. A token reader must not propagate that: an absent OIDC config is a state to handle, not an exception, and a throw here escapes the caller's `try` and leaves the permission set permanently undetermined.

---

## `EntityForm`: a `render` field's own setter must be stable, and the row re-seed must not race it

**Bug (freeze, no error)**: a create form built from a `render` field (§ *`EntityForm`* in `reusable.ui/widgets/STANDARD-PAGES.md`) hung the page until Playwright's own timeout. `EntityForm` passed each `render` field a fresh `(next) => setValue(field.name, next)` closure on every render; a `render` field that sets its own value from a `useEffect` depending on that closure's identity (the pattern the field exists for) therefore re-fired the effect every render, which re-rendered the form, which made a new closure — an infinite loop with no thrown error, invisible to `tsc` and to a manual read of the diff.

**Bug (silent 422, after the freeze was fixed)**: the form then opened and accepted input, but submitting it sent the API a request missing the `render` field's own value, rejected with a 422 the UI showed no error for. `EntityForm`'s "re-seed values when the edited row changes" effect — `useEffect(() => setValues(initial), [initial])` — fires on the component's OWN MOUNT too, because `initial` is a freshly built object on the first render just as much as on a later one. On mount this races the `render` field's own mount effect: React fires child effects before the parent's in the same commit, so the field's effect set its value first and `EntityForm`'s effect then unconditionally overwrote the whole `values` object back to `initial`, wiping what the field had just set moments earlier.

**Fix**:
- Cache one stable setter per field name (a `useRef` map, built lazily) instead of a fresh closure in the field-rendering loop, so a `render` field's effect depends on something that does not change across renders.
- Track the last `initial` the re-seed effect actually applied (another `useRef`) and only call `setValues(initial)` when that reference has genuinely changed — never on the render where `useState`'s own initializer already seeded `values` correctly.

**Rule**: a form field that derives its own value (rather than being typed by the viewer) must receive a setter whose identity is stable for the field's lifetime, and a form's own re-seed-on-row-change effect must not act on its first render. Neither defect is visible from source alone — the freeze needs a live render loop and the 422 needs a live submit — so a `render` field is worth exercising in a live-stack E2E spec, not just a component contract test.

---

## `StandardEntityPage`: a create/edit submit failure was an unhandled rejection, invisible to the viewer

**Bug (silent, no error shown)**: `EntityForm` calls a caller's `onSubmit` as `void onSubmit(values)` — it discards the promise because it cannot know whether a given caller's submit is worth awaiting the rejection of. `StandardEntityPage`'s own create/edit wiring, both for a page's main entity and for an association tab's `create`/`update`, relied on that promise resolving to close the dialog and refresh: `await transport.put!(...); setEditing(null); query.current?.refresh()`, with no `try`/`catch`. A rejected request therefore left the dialog open, the table unrefreshed, and nothing in the DOM, the console, or a screenshot to say why — the only place the failure existed at all was the network log. First found on `template_items_manager`'s standalone `sub_items`/`sub_item_notes` pages, whose CRUD E2E "UPDATE (UI)" test timed out waiting for the edited name to appear, with the edit dialog still fully populated and visibly unchanged in the failure screenshot.

**Fix**: every create/edit `onSubmit` in `StandardEntityPage` (the page's own entity, and each association level's `create`/`update`) wraps its transport call in a `try`/`catch`, sets a `formError` state on failure (rendered as a `role="alert"` line beside the form, the dialog staying open so the values aren't lost), and only calls `setCreating(false)`/`setEditing(null)` + refreshes on success. `formError` is cleared whenever a create/edit dialog is (re)opened or cancelled, so a stale message from a previous attempt never survives into the next one.

**Rule**: any `onSubmit` a `StandardEntityPage`-family widget passes to `EntityForm` must catch and surface its own transport call's rejection — never let it propagate into `EntityForm`'s `void onSubmit(values)`, which discards it silently. A submit path with no visible failure mode is untestable by a black-box E2E spec: the spec can only ever report "the expected result never appeared", not why.

---

## `StandardEntityPage`: a chain built from `row.id` breaks on a level whose rows are a join/grant row

**Bug (silent "No results", one hop deep)**: Depth visit's `select()` always wrote the selected row's OWN `id` into `AssociationChain` for a deeper level's `baseParams` to read (`chain[index + 1]?.id`). That is only correct when a level's rows ARE the referenced entity. A level reached through a join/grant table (e.g. host_app's Users page, whose Profiles level reads `as_user_profile`) has rows whose `id` is a SYNTHETIC composite of every key the association carries (`ideable_api.associations.synthetic_id(left_fk, right_fk[, scope_fk])` — `left_fk__right_fk[__scope_fk]`), never the referenced entity's own id. Selecting a Profile there and feeding the chain into the Roles level's `baseParams: { profile_fk: chain[1]?.id }` sent the grant's composite string (e.g. `"1__40__1"`) as `profile_fk`; the backend matched no row (or, on a strict endpoint, answered 422), and the very next tab read "No results" with nothing wrong in either level's OWN wiring on a static read — only the value written into the shared chain slot was wrong. Confirmed live against a deployed stack: `GET /api/as_profile_role?profile_fk=1__40__1&limit=1` → 422.

**Fix**: `AssociationLevel<Row>` gained an optional `chainId?: (row: Row) => string | number`. `select()` uses it in place of `row.id` when a level declares one. A page whose depth chain passes through a join/grant row supplies it (e.g. `chainId: (row) => row.profile_fk`); a page whose rows already ARE the referenced entity needs nothing (the default, `row.id`, stays correct).

**Rule**: before wiring a `depth` level's `baseParams` to `chain[n]?.id`, check what that level's OWN rows actually are. If they come from an association/join/grant endpoint (its response schema has a synthetic composite `id`, not the referenced entity's own primary key), declare `chainId` for that level — on BOTH halves it applies to, since a mode switch does not itself catch a level that never declared one. This is a property of the ENDPOINT the level's `query` reads, not of the caller's page, so it is worth checking on every new association level, not only ones that look like this one.

---

## Generated/maintained frontend config must not carry a deprecated TypeScript option

**Bug**: `tsconfig.json` in both host_app's and module_template's frontends set `"baseUrl": "."`
alongside `paths: { "@/*": ["./src/*"] }`. Under `moduleResolution: "bundler"`, `paths` alone
already resolves the alias — `baseUrl` contributes nothing and is the option TypeScript 6/7
deprecates for exactly this shape, so every frontend carried a defect that a future compiler
upgrade would turn into a hard failure with no warning beforehand.

**Fix**: Remove `baseUrl` and keep `paths` as the only alias mechanism:
```json
"compilerOptions": {
  "moduleResolution": "bundler",
  "paths": { "@/*": ["./src/*"] }
}
```
`tsc --noEmit` resolves `@/*` identically before and after — `paths` was already doing the work.

**Rule**: A generated or maintained frontend `tsconfig.json` must not declare `baseUrl` when
`paths` alone resolves every alias it declares (the case under `moduleResolution: "bundler"`,
the framework's own setting). More generally: a generated artifact — frontend or backend — must
pass its language's static gate (`tsc --noEmit`, `ruff`, `mypy`) before it is treated as valid.
A static-check violation is a build-breaking defect the moment it is introduced, never a "later
cleanup" item deferred past the change that introduced it.

---

## `AuthzContext`'s `me` query must not be keyed on the raw access token

**Bug (a redundant fetch burst on every silent token renewal)**: `AuthzProvider`'s `me` query used `queryKey: ["me", auth.user?.access_token]`. `App.tsx` silently renews the access token via the refresh-token flow every few minutes (`renewSessionSilently`, triggered by oidc-client-ts's `accessTokenExpiring` event) — the SAME session, a new token string. `useQuery` treats a changed key as a brand-new query: a live repro against a deployed stack (a row selected, an association tab open, watched for ~5.5 minutes matching the 5-minute access-token validity) caught one silent renewal firing a burst of 2–3× redundant re-fetches — the `me` query itself, and the active association level's `query`/`count` effects that this context's re-renders cascade into — for an answer that had not changed at all.

**Fix**: key the query on something STABLE across a renewal — this session dropped the token from the key entirely (`queryKey: ["me"]`), relying on `enabled: !!auth.isAuthenticated && !!auth.user?.access_token` for the initial fetch (already sufficient — `enabled` flipping true already triggers a fetch) and on `switchGrant`'s existing explicit `invalidateQueries` for the one case that legitimately needs a refetch (the active grant changed within the same session).

**Rule**: a query key names WHAT is being asked, not every value that happens to change alongside the session — an access token that rotates on a timer is the wrong thing to key an unrelated read on. If a query must differ by session, key it on something that changes only when the session actually does (a stable subject/session id), not on a credential that is expected to rotate while the session continues.
