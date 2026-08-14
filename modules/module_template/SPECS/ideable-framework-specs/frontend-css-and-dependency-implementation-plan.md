# Implementation plan: module dependency system + remote CSS loading

Tracked, checkbox-driven plan distilled from two design specs (kept on the working board
under `kanban/`): the **module dependency system** and the **remote-module CSS loading**
fix. Canonical contracts live in the spec files referenced below; this file tracks *what is
built vs pending*. Update the checkboxes in the same change that lands each item.

Legend: `[x]` done & verified · `[~]` partial · `[ ]` pending.

Canonical spec references:
- Dependency contract: `module-integration-specs.md` §5.1.
- CSS prefix/token pattern: `shared-ui-widgets-specs.md`, `framework-css-classes-reference.md`.
- CSS loading contract: `module-integration-specs.md` §2 (*CSS loading contract*).

---

## A. Module dependency system — Phase 1 (build + startup)  ✅ COMPLETE

- [x] `module.json` schema: `dependsOn[]` (typed `kinds` runtime/api/data/css/widgets, `optional`, `reason`) + `provides` (`css`/`api`/`widgets`, `gates`).
- [x] Resolver `scripts/common/module_deps.py`: implicit `host_app`, validation (target-enabled → hard error / `optional` skip, capability-provided, **acyclic**), providers-first topological order, `startup_edges()` kind-filter.
- [x] `build_and_deploy.py`: topological reorder of modules; build fails on unresolved/cyclic graph.
- [x] Generated cross-module `depends_on` — `compose_deps.py` **injects** the edges into the per-module *deployed* composes (root non-healthcheck services; deduped; gate-existence-guarded). Injecting into the per-module composes (not a separate override file) is required so the ordering survives **both** mergers: build-time `generate_merged_compose` **and** the runtime `create-merged-configuration.sh` (which re-merges per-module composes at redeploy and is override-file-unaware). **`create-merged-configuration.sh` must be kept** — it runs **standalone at deployed sites that have no `build_and_deploy.py`**, so the injected per-module composes (not a separate override file) are what carry the ordering there. Live-validated: the runtime merger preserves the generated `template-bootstrap` ordering.
- [x] Generator is the **sole authority** for module_template (hand-authored refs removed); validated live (`docker compose config` identical result).
- [x] Post-merge **guard**: build fails loudly if a generated edge is dropped from the merged compose.
- [x] `validate_modules.sh` runs the resolver and prints the order.
- [x] Contract tests (force-synced): `TESTS/test_module_dependency_resolver.py`, `TESTS/test_compose_deps.py`.
- [x] Docs: `module-integration-specs.md` §5.1, `IDEABLE-README.md` (*Inter-module dependencies*), `infrastructure-file-list.md`.

## B. Remote-module CSS loading in host_app  ✅ COMPLETE (live-validated)

The remote's compiled stylesheet must load when host_app mounts the module (not only in the
standalone `main.tsx`/`bootstrap.tsx` chain).

- [x] **§1 — `moduleManifest.ts` side-effect CSS import** (primary fix): `import './index.css'` at the top of the exposed manifest so the `./moduleManifest` expose carries the compiled stylesheet in its MF `assets.css`. Applied to the canonical `module_template` (tsc clean; manifest contract tests green).
- [x] **§4 — CSS loading contract** documented in `module-integration-specs.md` §2 (tracked spec).
- [x] **§3 — `module-init.sh` parity guard**: warn if a module's `moduleManifest.ts` lacks the `import './index.css'`.
- [x] **§2.2 — host_app runtime auto-injection**: `useRemoteModules.ts` reads a resolved remote's `mf-manifest.json` exposes' `assets.css` and injects `<link data-module-style="<slug>">` (deduped by attr/href, robust to hashed filenames). (§2.1 fixed-path `style` field intentionally **dropped**.)
- [x] **Artifact assertion**: `test_template_module_manifest_expose_carries_css` asserts the served `./moduleManifest` `assets.css` is non-empty (catches a regressed §1). **Live-validated**: the rebuilt template frontend's manifest carries `static/css/async/….css`.
- [x] **Test**: `tests/module-css-loaded.spec.ts` (force-synced, `RUN_STACK_E2E`) asserts a `/remotes/<slug>/…css` stylesheet is present when the module mounts inside host_app.

## C. Module dependency system — Phase 2 (runtime capability wiring)  ✅ CODE LANDED (tests partial)

Owned here (executed together with section B, since `kind:css` reuses §2.2). Consumes the
`dependsOn` edges already produced by Phase 1.

- [x] **Registry projection**: `_css_widget_deps_slugs` + `_apply_dep_projection` emit each module's declared css/widgets edges as provider slugs (`cssDependsOn`, `widgetDependsOn`) into `module-registry.json` (both registry generators).
- [x] **Deliverable A — `kind:css` cross-module injection**: `useRemoteModules.ts` injects the stylesheet of every provider in a module's `cssDependsOn` (reuses the §2.2 injector; deduped). host_app tsc clean.
- [x] **Deliverable B — `kind:widgets`**: providers are surfaced via `widgetDependsOn`; no new registration mechanism needed — a `dependsOn` target is a resolver-validated **enabled** module, already registered as an MF remote, so the dependent can `loadRemote('<provider>/<expose>')`.
- [~] **Tests**: registry projection covered by `TESTS/test_registry_dep_projection.py` (force-synced). Runtime cross-module injection covered by the §2.2 parser logic + host_app tsc; a browser-level assertion is pending (needs a live stack).
- [x] Dependency-system **Phase 2 code complete** — remaining gaps are the two *Pending* test/assertion items above, both requiring a live stack.
