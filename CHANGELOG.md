# Ideable Framework — Changelog

What changed in each published framework release, newest first. The format — the section heading,
the area blocks, the entry kinds and the three-line limit — is defined in `rules/version-control.md`
§ *A release says what it contains*. Sections are drafted by the `ideable-changelog` skill and
reviewed by the maintainer before `publish_framework.sh` runs; the publish refuses a release whose
version has no section here.

## 1.6.10 — 2026-09-28

### General framework rules

**New feature**
- `publish_framework.sh` now closes a release properly instead of only building and tagging: it
  refuses a release with no `CHANGELOG.md` section, tags `worklog/<version>` (full bookkeeping)
  before purging it, and tags the clean `<version>` on the purge commit.
  See `rules/version-control.md` § *A release archives how it was made, and hands back a clean tree*.
- `dev-cycle.sh new` now emits a plan's structural skeleton — the Mermaid graph, the timing columns,
  the legend, the decision markers and the Repos columns — instead of an agent transcribing them by
  hand, and moves the plan's kanban card `todo/` → `doing/` in the same step.
  See `rules/implementation-plan.md` § *Emitting a plan's skeleton*.
- A run that is getting nowhere now stops: a lap over a byte-identical codebase, a decision the node
  cannot take, and a router whose driver has gone are each detected and end the run instead of
  burning hours and quota while still reporting progress.
- A fast lane is now visible while it runs and holds the checkout: `dev-cycle.sh fastlane-start` and
  `fastlane-land` put a `fix/<description>` branch and a kanban card in flight under one lock per
  checkout, so a second worker — another fast lane, or a plan's `run` — is refused.
- A plan now declares every kanban card it implements (a `Kanban:` header) and `deliver` moves them
  all to `done/`, refusing a card that never reached `doing/`.
  See `rules/implementation-plan.md` § *The kanban card moves with the plan*.
- The router now asks its question through the process that started it when it has no terminal, so
  an agent-driven run reaches the person instead of recording a Blocked node and losing the child
  agent's context.

**Bug fix**
- The dev-tools container ran on `Etc/UTC` regardless of the host's timezone, so every timestamp
  the dev-cycle wrote (plan dates, filenames) was silently wrong for a maintainer not on UTC. It
  now forwards the host's IANA timezone at container creation.
- A frontend `tsconfig.json` carried a deprecated `baseUrl` alongside `paths`, inert under
  `moduleResolution: "bundler"` and one TypeScript upgrade away from a hard failure with no
  warning; removed, with a new static check enforcing the policy going forward.
- `test_a_run_is_watchable.py` failed inside the dev-tools container because its log path pointed
  outside the container's bind mount; the affected tests now use a repo-relative scratch
  directory the container can actually see.
- The CI gate never materialized a `local` module's `.env.secrets` from its `.example`, so a
  correctly fail-closed check always failed on a bare checkout; `gate.yml` now stubs it before
  the stack-free tests run.
- `deliver` and `.githooks/pre-push` now re-verify a bookkeeping-only diff with the same
  whole-suite-rerun pattern, so a delivery can no longer land a tree the newest recorded run called
  `FAILED`; a failed push names the bookkeeping it left behind and keeps the branch to retry.
  See `rules/version-control.md` § *Delivering a plan*.
- Three dev-cycle dead ends are closed: a plan whose sub-sets are all `Done` is no longer stuck at
  `Implementing` or `Documenting`, and a Repos row left unfinished no longer refuses `Done` forever.
- The router can now leave `Specs` once the targets are written, and a recorded spec gap routes back
  to `Specs` without an agent.
- The sub-set advance writes the plan through `_write_plan`, so the graph highlight, `Current step`,
  the iteration count and the execution clock stay consistent across a sub-set boundary.
- A recorded open decision now parks the plan at *Asking human direction* on the interactive path
  too, so the wait is measured and an agent at the keyboard can say the plan is waiting on a person.
- `pause` commits only what git tracks and names what it left, so an untracked board file can no
  longer vanish at the checkout and return as a duplicate through the merge.
- A plan is renamed `(Merged)` only when it is merged: a failed squash restores the branch tip
  instead of leaving a plan claiming a delivery that did not happen.
- `deliver` no longer measures its own certifying commit, so a plan whose work rode in the router's
  checkpoints lands with the right subject.
- The `Specs` cell is a per-iteration status — "the target is written" — not a verdict that survives
  the iteration.
- `schema.sh` re-derived a module slug that `module.json` declares, so it wrote to a directory that
  does not exist on a case-sensitive filesystem; it now reads the declared slug.
- `a` on Bash in the agent permission prompt now remembers the specific program, not the whole shell.
- The docs check read `CHANGELOG.md`'s historical entries as live claims; historical changelog
  entries are now exempt, like `kanban/` and `implementation-plans/`.

**Improvement**
- A node's timing is now its in-flight span since the transition that entered it, and waiting on a
  person gets its own `Ask` column, so the Sub-sets timing table shows where the time went rather
  than the router's own execution.
- The plan's status tables now describe the moment: entering a node marks its column, a test run
  certifies only the executing sub-set, and a finished sub-set is never repainted by a later
  sub-set's failures.
- `It #` now counts every pass of the build/test/fix loop, not only one of its two re-entry arcs.
- Specs now describe the present: the repository's prose no longer narrates how the system got to
  where it is. See `rules/implementation-plan.md` § *Documenting*.
- The plan format now reads per sub-set: decisions are one table per sub-set, a *General design*
  chapter holds the durable assumptions, and *Sub-sets timing* tracks time per dev-cycle state.

### host_app

**New feature**
- A module (host_app included) can now declare an entity and get a tenant-scoped, paginated,
  audited CRUD API and a standard master/detail page (`StandardEntityPage`) for free, without
  hand-writing backend or frontend code — reversible per entity, not an opt-in mode.
  See `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`
  § *The standard entity page*.
- Access is now governed by a `(tenant, profile)` grant: a user acts under exactly one tenant and
  profile at a time, profiles hold roles (never a tenant directly), and a per-tenant
  `security_officer` role can administer that tenant's own users, grants, roles and profiles.
  What a module reads from host_app (active tenant, active profile's permissions) is unchanged.
  See `modules/host_app/SPECS/auth-specs.md` § *The active grant decides the answer*.

**Bug fix**
- The Users/Roles/Profiles admin pages' association view (Depth visit / Full perspective)
  resolved and labeled associations incorrectly, a column sort could empty the table, and several
  filters did not filter. Rebuilt on the standard entity page, which fixed all of it.
- External URLs (the OIDC issuer, Traefik routing rules, the ACME challenge) were derived by
  guessing instead of from configuration, so login could fail on a stack not running on the
  default port. They now derive from `EXTERNAL_BASE_HOST` and the configured port.
- A `__filterable__` boolean column was filtered with `ILIKE`, which Postgres refuses outright;
  booleans are now an exact match, and the DDL check no longer demands a trigram index for one.
- The framework's `before_create` hook was declared and documented but never wired, so no entity
  could have a create-time side effect; host_app's `users` — which must write both Authentik and
  the local row — is the entity that needed it.
- The ACME challenge method could not be stated at all, so a second stack on one host could not
  renew its certificate; it is now configurable.

**Improvement**
- host_app now has a browser-level Playwright e2e suite covering its admin pages, in addition to
  the existing source-level contract tests.

### Dev Toolbox

**New feature**
- The Claude subscription token can now be carried into the toolbox without a hand-typed export:
  `claude_token.sh --mint` runs `claude setup-token` visibly and stores the result in the platform
  keystore, and the router fills `CLAUDE_CODE_OAUTH_TOKEN` from it when it is unset.

**Bug fix**
- The toolbox container could keep using a stale git credential after the credential was rotated,
  because only the token value was refreshed and not the helper wiring around it.
- `verify_remote_shape.sh` could fail spuriously: a stripped environment variable caused it to
  start a nested toolbox container whose cache mount was unreachable.
- The toolbox now recreates itself when its credential wiring no longer matches the invocation, so
  a container first started without the helper can still authenticate.
- `verify_remote_shape.sh` now reports which test failed, not only a count.

**Improvement**
- The shipped tooling now passes where it lands: `verify_remote_shape.sh` went from 27 failing test
  files in a remote-shaped project to none, fixed rather than skipped.

### Module Template

**New feature**
- A worked example of a related-entity chain (`sub_items` → `sub_item_notes`) now ships alongside
  `items`, demonstrating the standard entity page end to end for both a main and an association
  entity. See `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`
  § *The association view*.

**Bug fix**
- `sub_items` and `sub_item_notes` had no standard page of their own, reachable only through their
  parent's association view. Every datamodel entity now gets a standard page by default.
- The Items page's own association view stopped one hop short of the datamodel's actual chain:
  selecting an item, then one of its sub-items, never surfaced that sub-item's own notes.
- The Playwright e2e config silently exercised a synthetic shell instead of the real deployed
  stack, because it read an environment variable nothing set.

## 1.6.9 — 2026-09-16

### General framework rules

**New feature**
- `deliver` now refuses before it changes anything when the plan it is about to land does not
  actually qualify, instead of refusing partway through.

**Bug fix**
- `latest` now moves only after every other step of a publish has succeeded, instead of
  potentially naming a half-published release.

### Dev Toolbox

**Bug fix**
- The devtools image was missing `docker-buildx-plugin`, so a build the toolbox itself owns
  could fail; it is now installed and asserted by `--doctor`.

## 1.6.8 — 2026-09-14

### General framework rules

**Bug fix**
- A corrected `host_app/.env.config` default (including the identity-plane database host) now
  actually reaches a remote that already adopted an earlier version, instead of only new installs.
- The i18n override report now judges a translation key a no-op across every language at once
  instead of per language, so a key overridden in one language and merely coincidental in another
  is no longer misreported as removable.

### Dev Toolbox

**New feature**
- The dev tools image now ships the Claude Code CLI alongside its Python SDK, since the router
  needs both to actually run; the credential reaching the container is forwarded as an
  environment variable rather than mounted or baked into the image.

## 1.6.6 — 2026-09-13

### General framework rules

**New feature**
- A paused plan now shows on the kanban board, not only in git.

**Bug fix**
- The dev-cycle status probe now accepts both shapes of a router that already ran, instead of
  only one.

## 1.6.5 — 2026-09-09

### General framework rules

**Bug fix**
- The sync script now runs from a copy of itself, since it is one of the files it syncs and could
  otherwise be replaced mid-run; `adopt_framework.sh` now survives that same replacement.
- The push gate now allows a release commit to be pushed, and resolves "the latest run" by name
  instead of an assumption that could pick a stale one.

## 1.6.4 — 2026-09-09

### General framework rules

**Improvement**
- Publishing now requires the version on both the publish and adopt sides, `latest` included,
  closing a gap where a mismatched version could be adopted silently.

**Bug fix**
- `adopt_framework.sh` now installs the release's own lock file immediately instead of waiting
  for a subsequent sync, and `publish_framework.sh` now actually pushes a release instead of
  potentially leaving it built on one machine only.

### Dev Toolbox

**Bug fix**
- A locked image digest is now looked for among all of the image's digests instead of only the
  first, fixing spurious adoption failures.

## 1.6.3 — 2026-09-09

### General framework rules

**New feature**
- Backups: a backup/restore/verification toolchain with a runbook, later hardened to cover the
  identity plane (which had no working backup since it was introduced), to verify the framework
  version before restoring, and to restore TimescaleDB hypertables intact.
- Observability: structured JSON logs, request-correlation ids and Prometheus metrics across
  host_app and module_template.
- Schema is now the model: Alembic migrations replace `create_all`/hand-written DDL for both
  host_app and module_template, and migrations run as a deploy-time job before the app starts.
  See `database/SPECS/ideable-framework-specs/schema-workflow.md`.
- Backend database connection pools are now explicitly sized with concurrency controls, in both
  host_app and module_template, instead of relying on driver defaults.
- Query performance: trigram search indexes and keyset pagination on list endpoints, and item
  audit history now paginates in SQL instead of in Python.
- Audit tables are now time-partitioned with a configurable retention policy, and the audit
  reference instant is persisted rather than derived (and previously silently wrong on failure).
- Tenant scoping is enforced by default in the template, and a tenant's scope is now resolved
  from `/api/me` instead of being carried in the JWT.
- Horizontal scale: replicable services, rolling deploy, and documented, honest resource limits.
- Identity high availability: a dedicated identity database, cache and replicas with decoupled
  startup, and a hot-rotatable file-based backend credential; later re-based on Postgres, dropping
  a Redis dependency the design never actually needed.
- An entity's framework DDL (versioning, partitioning, RLS) is now emitted from its SQLAlchemy
  model instead of hand-written, and the build now fails when a model and its DDL disagree, or
  when a table's row-level security has nothing actually constraining it.
- Cloud-ready runtime: the application is PID 1 and honours SIGTERM, images are distroless,
  non-root and read-only-rootfs with digest-pinned bases and immutable per-commit tags, and
  startup now fails fast on bad configuration with outbound calls bounded.
- `ruff`, `mypy` and `tsc` now gate the build instead of running informationally.
- The dev-cycle router now delivers a plan as its declared sub-sets, running one loop pass per
  sub-set with `Current step` naming which one is active, and a plan starts at `NotStarted` with a
  `Branching` step creating its branch.
- A fast lane now exists for a change simple enough to need no implementation plan (the
  maintainer decides the route), and `deliver --pr` can open a pull request instead of squashing
  straight onto `main`.
- The router now streams the driven agent's progress into the plan, folds its commits in as it
  goes, owns the conversation with that agent end-to-end (one question at a time, refusing a
  second agent on a plan already in flight), and records what each run cost.
- A plan's filename always carries its latest execution timestamp, so every active plan has one
  stable, unambiguous name.
- Every push is now gated on the stack-free test suite, matched locally by a self-enabling
  pre-push hook, with a deliberate, recorded override for when the gate must be bypassed; the
  local and remote gates were brought into parity, including in remote module projects.
- Publishing a framework release and a remote adopting one now each name the version in exactly
  one place (`publish_framework.sh <version>`, `adopt_framework.sh <version>`), replacing a
  previous two-step hand-edit-then-sync process.

**Improvement**
- Compose hygiene: restart policies, resource limits, database ports bound to loopback, and
  bounded log sizes across every module's compose files.
- A module frontend build now installs from its committed lockfile, so a commit reproducibly
  rebuilds itself, and an image build context that had been leaking compiled bytecode (and could
  have leaked credential-shaped files) no longer does — the credential-pattern check is recursive.
- A generated remote module can now be built and pass its own suite from its specs alone: the
  template sync no longer produces artifacts describing the wrong module, and the FK-dependency
  graph and CRUD generator work off the schema actually given, not assumptions baked in from host_app.

**Bug fix**
- An empty required environment variable now fails a deploy the same way a missing one does, and
  an env value containing spaces (breaking audit-retention configuration) is now quoted correctly.
- A failed deploy now exits non-zero instead of reporting success.
- The test runner's reported pass/fail verdict now always matches its process exit code — a
  suite that crashed or never ran could previously read back as a green, zero-test pass.
- `deliver` now certifies the commit it actually produced and reports what happened to the plan
  branch at every location that touches it, instead of occasionally drifting ahead of what was
  tested.

### host_app

**New feature**
- Authorization is now backed by host_app's own SQL tables (roles, permissions, associations)
  instead of being mirrored into Authentik: the token carries identity only, and the admin API,
  the frontend and every remote module resolve permissions from a cached `/api/me`.
- Granting or revoking access — directory sync, JIT provisioning, self-registration — now takes
  effect without a redeploy; an Admin → System messages page reports anything a seed could not
  apply because an operator had removed it.
- "My access" now shows the whole resolved `/api/me` — identity, active/available profiles and
  every permission grouped by owning module — under a new "Insights" menu group alongside System
  messages and Access logs.

**Bug fix**
- A deprovisioned user lost host_app authorization immediately instead of keeping stale access
  after the identity source removed them, and a mixed-case username no longer causes the
  deprovisioning reconcile to mistakenly deactivate a live account.

### Module Template

**Bug fix**
- A remote module's frontend was sending a stale session token, so a permission its user
  actually held could read back as a denial; it now sends the current session's token.

## 1.5.0 — 2026-08-14

### General framework rules

**New feature**
- The dev-cycle now has a thin deterministic router (`dev-cycle.sh`) driving a shared
  implementation-plan artifact through the skill graph: it auto-invokes LLM nodes by default,
  chains steps with `--auto-advance`, and gives each plan its own `plan/<description>` branch.
  See `rules/implementation-plan.md` and `scripts/README.md`.
- `ideable-spec-driven-edit` is now the one atomic safe-edit discipline every code/config
  change routes through (implement, test-and-fix, bugfixing), and an incremental spec
  work-set (`spec_workset.py`) scopes `ideable-implement-specs` runs to what actually changed.
- A per-module dependency system: `module.json` now declares typed `dependsOn`/`provides`
  edges (runtime/api/data/css/widgets), resolved providers-first at build time with
  cycle/capability validation and generated cross-module compose `depends_on`.
  See `module-integration-specs.md` §5.1.
- Module edge routing: `module.json routes[]` lets a module declare extra Traefik routes
  and a separate backend API origin (`apiUpstream`) for sub-remotes or external origins,
  validated fail-closed against prefix collisions.
- The test runner is now the single sanctioned entry point (direct pytest/Playwright is
  blocked unless explicitly opted into) and produces human-readable, colour-cued reports; a
  force-synced Playwright suite gives every remote authenticated UI and CRUD E2E for free.
- `reusable.ui` (`@ideable/ui`) is now the single shared widget/design-token library
  consumed by host_app, module_template and every remote — including a runtime
  `config/theme-override.css` rebrand path needing no image rebuild.
  See `reusable.ui/README.md` and `look-and-feel-branding.md`.
- Project/module environment files are now split into `.env.config` (ports, paths, params)
  and `.env.secrets` (passwords, tokens, keys), with matching bootstrap, merge and
  validation across `build_and_deploy.py`, `redeploy.sh` and the deployable-update flow.
- The deployable-bundle workflow (`update-deployable.sh`, `create-merged-configuration.sh`,
  `configure.sh`, git push/pull scripts) gained interactive env-conflict merging with
  cross-file decision memory and auto-registration of newly pulled modules.

**Bug fix**
- A redeploy could silently drop generated cross-module container startup ordering, because
  the runtime compose merge ran again after build and was unaware of the generated override.
  Edges are now injected directly into each module's deployed compose, with a build-time guard.
- `sync-template-updates.sh` repeatedly mis-handled `.env.*.example` files (deleted them on
  rename detection, re-reported already-removed files, mangled git-rename paths with
  embedded tabs) and could re-add files in a loop; all fixed so repeated syncs converge.
- `create-merged-configuration.sh` had several env-merge correctness bugs: `DATABASE_URL`
  miscategorised (breaking `stop.sh`), cyclic env-var references causing infinite recursion,
  and module customizations being overwritten by root defaults on merge.
- Duplicate-port and duplicate-key startup failures: `adjust-exposed-ports.sh` now detects
  two env vars claiming the same host port, and Postgres `SERIAL` sequences are resynced to
  `MAX(id)` after a restore so inserts no longer collide.
- OIDC token refresh returned 405 because the token endpoint was guessed instead of read
  from OIDC discovery/pinned metadata — fixed across the shared auth config.

**Improvement**
- Modules and their repos were renamed from PascalCase (`HostApp`/`ModuleTemplate`) to
  snake_case (`host_app`/`module_template`); wire slugs (`hostapp`/`template`) are unchanged.
- Frontend stack upgraded to React 19, Tailwind CSS v4 (colon-prefixed utility syntax) and
  Rsbuild 2.x across host_app and module_template.
- Docker image/registry naming was unified (`{APP_SLUG}.{MODULE_SLUG}.<submodule>`,
  slash-in-compose `MODULE_DOCKER_REGISTRY_PREFIX` convention) and `redeploy.sh` gained a
  progress spinner, per-step timing and a `--verbose` flag.
- `rules/general-guidelines.md` now documents the framework-owned "never modify in remote
  projects" file list, and every remote-facing CSS class gets a canonical reference doc
  (`framework-css-classes-reference.md`) for rebranding.

### host_app

**New feature**
- Authorization is now backed entirely by Authentik as the source of truth for
  profiles/roles/permissions (no local shadow tables); audit-trail history endpoints are
  paginated server-side and password changes are now tracked in user history.
- The Permissions table gained a "Module" column, and the audit trail (users/roles/
  profiles/tenants) is now filterable per column, matching the module_template contract.

**Bug fix**
- The audit-trail "who" filter silently filtered by the wrong actor because a loop-local
  variable shadowed the query parameter of the same name.
- `env-config.js` (per-deployment OIDC runtime config) was served with a year-long
  immutable cache header, so a client could keep using a previous deployment's OIDC config
  after redeploy and fail to log in; it is now served `no-store`.
- Silent OIDC token renewal could blank the UI or fail with a 405 (wrong/guessed token
  endpoint, IdP session polling side effects); both are fixed.
- The Authentik bootstrap now re-runs on every start so it stays in sync with the deployed
  `authorization.yaml`, and a service-account token now correctly carries the superadmin
  claim needed for backend integration tests.
- Several sidebar/menu bugs: the Admin section could render with nothing behind it, the
  menu could build before remote-module data finished loading, and Authentik's own internal
  groups (`authentik-*`) leaked into the selectable profile list.
- `GET /api/roles/{id}` raised a 500 (missing DB dependency), and access-log sorting was
  client-side only; both are now correct and server-side sorted.
- The UUID→integer ID mapping used for audit history was kept only in a temp file and lost
  on container restart, causing mixed/duplicate history entries; it is now a persisted table.

### Module Template

**New feature**
- A `TimeSeriesChart` widget (line/area, token-themed, data-driven) is now part of the
  shared widget set, demonstrated in the (build-flag-gated, dev-only) Widget Gallery.

**Bug fix**
- `menu_definition.json`'s `authorization_claim` didn't match the slug-substitution scheme
  used by `module-init.sh`, breaking menu access after initializing a new module from the
  template.
- The audit-trail table was a hand-rolled `<table>` that missed framework features (column
  resize, dark-mode chrome) and drifted from spec; it now uses the shared `ServerDataTable`,
  and popups/dialogs no longer render white-on-white in dark mode.

**Improvement**
- Entity-table row-action icons (view/edit/delete/history/unlink) are now unified across
  host_app, module_template and every remote via a shared `RowActionButton` widget, and
  table columns are now user-resizable with double-click auto-fit.

## 1.4.0 — 2026-06-12

### General framework rules

**New feature**
- A dedicated `ideable-bugfixing-and-changes` skill now exists for the fast-lane
  change/bugfix workflow.

**Improvement**
- Audit trail `au_*` columns are now sourced from SQLAlchemy-Continuum's
  `TransactionMetaPlugin` instead of hand-maintained columns.

## 1.3.0 — 2026-06-10

### General framework rules

**Improvement**
- Template sync/push scripts now correctly handle already-updated files and README files,
  force-sync `base-specs.md`/`IDEABLE-README.md`, and explicitly sync `authorization.yaml`
  instead of silently dropping it.
- Bootstrap scripts are now baked into the image for remote projects instead of relying on a
  DIST fallback, and Authentik blueprint generation now happens inside the bootstrap container.

**Bug fix**
- Authentik bootstrap now resolves its blueprint script source correctly for both main-repo
  development and remote projects, and Authentik flow-lookup UUID resolution and compose
  variable escaping were fixed.

### host_app

**New feature**
- An audit trail contract now spans the framework (base specs + UI), with refined display
  and fixed history endpoints.
- `menu_access` permissions are now enforced explicitly, the superadmin flag now syncs to
  Authentik via group membership, and "companies" were renamed to "tenants" end-to-end
  (JWT claim `hostapp.tenant_ids`).

**Bug fix**
- Login page visibility, menu routing and a frontend script issue were fixed; the Users
  page's Full perspective now resolves correctly; and Authentik's own internal accounts
  (`akadmin`, `ak-outpost-*`) no longer appear in the Users page.

## 1.2.2 — 2026-05-26

### General framework rules

**Bug fix**
- Fixed a container start problem on a remote host.

## 1.2.1 — 2026-05-26

### General framework rules

**Bug fix**
- The authorization plan now rebuilds only on redeploy, instead of unnecessarily more often.

### host_app

**Improvement**
- A module can now nest items inside host_app's own main menu items instead of only appending
  a flat entry, and sub-menu indentation was fixed.

### Module Template

**Improvement**
- The YAML contract in `base-specs.md` was relaxed.

## 1.2.0 — 2026-05-26

### host_app

**New feature**
- OIDC silent token renewal and claim-based authorization are now implemented.

**Improvement**
- The custom silent-renew implementation was replaced by the standard OIDC flow.

**Bug fix**
- `companies:view`/`companies:edit` permissions were missing, and several frontend
  authorization bugs were fixed.

## 1.1.0 — 2026-05-23

### General framework rules

**New feature**
- Multi-arch image builds and pushes, documented and hardened for the release process.

**Improvement**
- Template sync now skips branding files (favicon, login background, home page) by default,
  with an `--all` flag to force them, and the authorization merge process is now more
  remote-friendly.

**Bug fix**
- Dot-format permissions now auto-migrate, `generate_authentik_blueprint.py` now ships to
  remote projects instead of only existing in the main repo, and template push force-adds
  `DIST` directories so `.gitignore` can no longer silently exclude them.

### host_app

**New feature**
- Authorization is now centralized in Authentik: a registry-model refactor replaced the legacy
  profile claim, "Companies" were added to the UI and token, and Users/Roles-to-Profiles
  mapping at bootstrap time now work correctly.
- Available profiles are now persisted in Authentik instead of only in memory.

**Bug fix**
- A module's menu mapping could overwrite another module's instead of merging with it, and
  JWT token generation is now correct.

## 0.0.1 — 2026-05-07

### General framework rules

**New feature**
- Multi-module monorepo layout: scripts split into `module_only/` (synced to remote module
  repos), `master_only/`, `common/` and `runtime/`; `build_and_deploy.py` builds SOURCES into
  DIST and deploys to `deployment_root/`, materializing runtime config and merging compose/`.env`.
- A template sync/push workflow lets a remote module repo pull infrastructure updates and push
  module-specific changes back; `module-init.sh` scaffolds a brand-new module by renaming the
  template's slug/name across files, filenames and env vars, and registers it in `enabled.md`.
- Repo-root `project.env` centralizes project-wide config separately from per-module env files;
  each module gets a `config/` folder for runtime-mounted files (menu mapping, branding, login
  background) deployed via copytree.
- Container/image naming convention: dotted `${APP_SLUG}.${MODULE_SLUG}.<service>` container
  names and `{app_slug}/{service}` image names, enforced by contract tests, with template sync
  auto-migrating older container names to the new pattern.
- Generic, APP_SLUG/datamodel-introspection-driven contract tests (L&F parity, i18n, auth
  permissions payload, datamodel/authorization source sync) are synced to every module so the
  same suite runs unmodified in HostApp, ModuleTemplate and any remote.

**Bug fix**
- Deployment could require a manual `docker network create` on a fresh environment; networks
  are now auto-created by stripping the compose `external: true` flag.
- Module Federation resolved a remote's relative manifest URL against a hardcoded build-time
  host instead of the browser origin, breaking any deployment not on `localhost:3000`.
- ModuleTemplate's compose hardcoded `TIMESCALEDB_VERSION` instead of reading it from the
  merged `.env`, letting modules run mismatched Postgres/TimescaleDB versions.

### host_app

**New feature**
- Authorization model: roles, profiles and permissions with many-to-many associations, backed
  by Authentik for authentication and PostgreSQL for authorization, enforced from a user's
  active role/profile, with self-service `/api/me` endpoints and a deterministic sadmin bootstrap.
- Data tables: `ServerDataTable`/`AssociationServerDataTable` widgets with server-side
  sort/filter/pagination, a vertical drill-down entity page pattern (table → details card →
  tabbed associations) applied across Users/Profiles/Roles/Permissions, and an audit-data toggle.
- The Authentik login page is rebranded (transparent popup, Ideable logo/favicon, title
  override), and the frontend gains i18n (English/Italian) and dark-mode theming.
- Swagger UI gets OAuth2/PKCE wired against Authentik, including a module-scoped redirect
  callback so remote modules' API docs authenticate the same way.
- Session handling: silent OIDC token renewal on 401 (falling back to interactive login only if
  silent renew fails) avoids a visible login flash, and the session stays alive on activity.

**Bug fix**
- The Permissions table's pagination did not reset when its filter changed.
- The "Active Role" table cell used a full page reload instead of client-side routing,
  occasionally triggering an OIDC redirect loop.
- Toggling dark mode didn't apply the `dark` class to the document, leaving pages stuck in
  light mode.

### Module Template

**New feature**
- ModuleTemplate ships as a self-contained, standalone module blueprint (frontend/backend/
  database/tests/specs), independently runnable and compatible with the HostApp integration
  contract out of the box, with its entities database persisting across redeploys.
- Session/auth in a remote module defers entirely to HostApp-managed OIDC renewal rather than
  implementing its own recovery flow, per the shared UI spec.

**Bug fix**
- ModuleTemplate's UI (icons, CSS scoping) drifted from HostApp's look & feel; hardcoded SVG
  icons were replaced with the shared `lucide-react` set and Tailwind class prefixes made
  consistent, verified by new Playwright visual-parity and contract tests.
- A missing `seed.sql` volume mount left a freshly initialized module without its seed data.
