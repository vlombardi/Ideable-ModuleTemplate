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

**Rule**: never hand-edit `traefik/SOURCES/dynamic.yml.template` or `deployment_root/modules/host_app/traefik/dynamic.yml.template`. The source of truth is the generator in `scripts/common/build_and_deploy.py` (the frontend container port is the `FRONTEND_CONTAINER_PORT` constant there). A file that looks like a source and is regenerated is worth checking for before editing anything under `SOURCES/`.

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
