#!/usr/bin/env python3
"""Inter-module dependency resolver — Phase 1 of the module-dependency system.

Each module declares, in its ``module.json``, the other modules it depends on:

    {
      "provides": { "css": true, "api": true, "widgets": [] },   // optional
      "dependsOn": [
        { "module": "report_generator", "kinds": ["api"], "optional": false,
          "reason": "SRA calls report_generator to render PDFs" }
      ]
    }

This module parses those declarations for the enabled set, validates them, and returns a
topological order (providers first). It is imported by ``build_and_deploy.py`` (to order
the build/iteration) and invoked as a CLI by ``validate_modules.sh`` and the contract test.

Decisions (see kanban module-dependency-system-spec.md):
- Lives in ``module.json`` (no new file).
- ``host_app`` is an implicit universal dependency of every non-host module.
- A missing required target is a HARD ERROR; an edge marked ``"optional": true`` degrades
  to a warning and is dropped.
"""
from __future__ import annotations

import json
import os
import re
import sys

HOST_MODULE = "host_app"
VALID_KINDS = {"runtime", "api", "data", "css", "widgets"}
# Kinds that name a capability the target must `provide` (runtime/data are pure ordering).
CAPABILITY_KINDS = {"api", "css", "widgets"}
# Kinds that imply a container START-order dependency (css/widgets are runtime-frontend only
# and must NOT gate container startup).
STARTUP_KINDS = {"runtime", "api", "data"}


class ModuleDepError(Exception):
    """Raised when the dependency graph cannot be resolved (missing target, missing
    capability, invalid kind, or a cycle)."""


def read_enabled_modules(modules_dir: str) -> list[tuple[str, str]]:
    """Parse ``modules/enabled.md`` into a list of (module_name, mode) in file order."""
    enabled_path = os.path.join(modules_dir, "enabled.md")
    out: list[tuple[str, str]] = []
    if not os.path.isfile(enabled_path):
        return out
    with open(enabled_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(local|remote)\s*$", line, re.IGNORECASE)
            if m:
                out.append((m.group(1), m.group(2).lower()))
    return out


def _read_module_json(modules_dir: str, name: str) -> dict:
    path = os.path.join(modules_dir, name, "module.json")
    if not os.path.isfile(path):
        return {"name": name}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _provides(meta: dict) -> dict:
    """Resolve a module's provided capabilities, applying sensible defaults:
    css=True when it has a frontend, api=True when it has a backend."""
    declared = meta.get("provides") or {}
    return {
        "css": declared.get("css", bool(meta.get("frontendPort"))),
        "api": declared.get("api", bool(meta.get("backendPort"))),
        "widgets": declared.get("widgets", []),
    }


def _toposort(names: list[str], deps: dict[str, set[str]]):
    """Stable Kahn-style topological sort — a module is emitted only once ALL modules it
    depends on are emitted, so providers come first. Ties break by original order.
    Returns (order, cycle_members): cycle_members is None when acyclic, else the modules
    that could not be ordered.

    (Same algorithm as the FK entity graph in
    frontend/TESTS/playwright/lib/entity-graph.ts — kept in parity across the two.)"""
    emitted: list[str] = []
    seen: set[str] = set()
    progress = True
    while progress and len(emitted) < len(names):
        progress = False
        for n in names:  # original order → stable
            if n in seen:
                continue
            if all(d in seen for d in deps[n]):
                emitted.append(n)
                seen.add(n)
                progress = True
    if len(emitted) != len(names):
        return emitted, [n for n in names if n not in seen]
    return emitted, None


def resolve(enabled: list[tuple[str, str]], modules_dir: str) -> dict:
    """Resolve the dependency graph for the enabled set.

    Returns ``{"order": [...], "edges": {module: [deps]}, "warnings": [...]}`` where
    ``order`` is providers-first topological. Raises :class:`ModuleDepError` on any
    unresolved required edge, invalid kind, or cycle.
    """
    names = [n for n, _ in enabled]
    nameset = set(names)
    metas = {n: _read_module_json(modules_dir, n) for n in names}
    provides = {n: _provides(metas[n]) for n in names}

    deps: dict[str, set[str]] = {n: set() for n in names}
    edge_kinds: dict[str, dict[str, set[str]]] = {n: {} for n in names}
    errors: list[str] = []
    warnings: list[str] = []

    for n in names:
        for edge in metas[n].get("dependsOn", []) or []:
            target = edge.get("module")
            kinds = edge.get("kinds", []) or []
            optional = bool(edge.get("optional", False))

            if not target:
                errors.append(f'module "{n}" has a dependsOn entry with no "module" field')
                continue

            bad_kinds = [k for k in kinds if k not in VALID_KINDS]
            if bad_kinds:
                errors.append(
                    f'module "{n}" dependsOn "{target}" has invalid kind(s) {bad_kinds}; '
                    f"valid kinds: {sorted(VALID_KINDS)}"
                )

            # Prerequisite must be enabled (decision 3).
            if target not in nameset:
                msg = (
                    f'module "{n}" dependsOn "{target}" '
                    f'(kinds: {", ".join(kinds) or "-"}), but "{target}" is not enabled in '
                    f"modules/enabled.md.\n"
                    f'       → enable it, or mark the dependency "optional": true.'
                )
                if optional:
                    warnings.append(f"optional dependency skipped — {msg}")
                    continue
                errors.append(msg)
                continue

            # Target must provide every requested capability kind.
            missing = []
            for k in kinds:
                if k not in CAPABILITY_KINDS:
                    continue
                if not provides[target].get(k):
                    missing.append(k)
            if missing:
                msg = (
                    f'module "{n}" dependsOn "{target}" for kind(s) {missing}, but '
                    f'"{target}" does not provide them (module.json "provides").'
                )
                if optional:
                    warnings.append(f"optional dependency degraded — {msg}")
                else:
                    errors.append(msg)
                    continue

            deps[n].add(target)
            edge_kinds[n].setdefault(target, set()).update(kinds)

        # Implicit universal dependency on host_app (decision 2) — only if host_app is
        # itself in the enabled set. Treated as a runtime (startup-gating) dependency.
        if n != HOST_MODULE and HOST_MODULE in nameset:
            deps[n].add(HOST_MODULE)
            edge_kinds[n].setdefault(HOST_MODULE, set()).add("runtime")

    if errors:
        raise ModuleDepError("\n".join("ERROR: " + e for e in errors))

    order, cycle = _toposort(names, deps)
    if cycle:
        raise ModuleDepError(
            "ERROR: dependency cycle detected among modules: " + ", ".join(sorted(cycle))
        )

    return {
        "order": order,
        "edges": {k: sorted(v) for k, v in deps.items()},
        "edge_kinds": {k: {d: sorted(ks) for d, ks in edge_kinds[k].items()} for k in names},
        "warnings": warnings,
    }


def startup_edges(result: dict) -> dict:
    """From a :func:`resolve` result, return ``{module: [providers]}`` keeping only edges
    that imply a container START-order dependency (kinds ∩ {runtime, api, data}). css/
    widgets-only edges are runtime-frontend and are excluded from startup gating."""
    out: dict[str, list[str]] = {}
    for module, per_dep in result.get("edge_kinds", {}).items():
        out[module] = [
            dep for dep, kinds in per_dep.items() if set(kinds) & STARTUP_KINDS
        ]
    return out


def _slug_of(name: str, meta: dict) -> str:
    return (meta or {}).get("slug") or name.lower().replace("_", "")


def _has_backend(modules_dir: str, name: str, meta: dict) -> bool:
    if meta.get("backendPort"):
        return True
    return os.path.isdir(os.path.join(modules_dir, name, "backend"))


def _rsbuild_exposes(modules_dir: str, name: str):
    """Return the set of MF-exposed names (from `'./Name': …` in rsbuild.config.ts), or
    None when the config can't be read (validation then skips widget checks)."""
    path = os.path.join(modules_dir, name, "frontend", "SOURCES", "rsbuild.config.ts")
    if not os.path.isfile(path):
        return None
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    return set(re.findall(r"""['"]\./([A-Za-z0-9_]+)['"]\s*:""", text))


def validate_provides(enabled: list[tuple[str, str]], modules_dir: str) -> list[str]:
    """Point 1 — lint declared `provides` against reality (build-time, warn-only):
    - `provides.api == true` but the module ships no backend (no `backend/`, no backendPort);
    - `provides.widgets: [Name]` not actually exposed as `./Name` in rsbuild.config.ts."""
    warns: list[str] = []
    for name, _ in enabled:
        meta = _read_module_json(modules_dir, name)
        prov = meta.get("provides") or {}
        if prov.get("api") is True and not _has_backend(modules_dir, name, meta):
            warns.append(
                f'module "{name}" declares provides.api=true but has no backend '
                f"(no backend/ folder and no backendPort)"
            )
        widgets = prov.get("widgets") or []
        if widgets:
            exposed = _rsbuild_exposes(modules_dir, name)
            if exposed is not None:
                for w in widgets:
                    if w not in exposed:
                        warns.append(
                            f'module "{name}" declares provides.widgets "{w}" but '
                            f'rsbuild.config.ts exposes no "./{w}"'
                        )
    return warns


_SRC_EXTS = (".ts", ".tsx")

# A cross-module Tailwind class is `<slug>:[variants:]<utility>`. Match only real utility
# roots so we don't flag `<slug>:`-prefixed CustomEvent names / string keys (e.g.
# "hostapp:language-changed") as CSS usage. Optional leading variants (hover:, md:, …).
_CSS_VARIANTS = r"(?:[a-z][a-z0-9-]*:)*"
_CSS_UTIL = (
    r"(?:bg-|text-|border|rounded|shadow|opacity-|ring|outline|transition|cursor-|overflow"
    r"|flex\b|grid\b|gap-|items-|justify-|inline|block\b|hidden\b|absolute\b|relative\b|fixed\b|sticky\b"
    r"|z-|top-|bottom-|left-|right-|font-|leading-|tracking-|whitespace-|space-|divide-"
    r"|w-|h-|min-|max-|p-|px-|py-|pt-|pb-|pl-|pr-|m-|mx-|my-|mt-|mb-|ml-|mr-)"
)


def _read_frontend_src(modules_dir: str, name: str) -> str:
    root = os.path.join(modules_dir, name, "frontend", "SOURCES", "src")
    if not os.path.isdir(root):
        return ""
    chunks: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(_SRC_EXTS):
                try:
                    chunks.append(open(os.path.join(dirpath, f), encoding="utf-8", errors="replace").read())
                except OSError:
                    pass
    return "\n".join(chunks)


def drift_lint(enabled: list[tuple[str, str]], modules_dir: str) -> list[str]:
    """Point 2 — drift lint (warn-only): compare a module's *actual* cross-module usage to
    its declared `dependsOn`:
    - uses another module's `<slug>:` Tailwind classes but doesn't declare a `css` edge;
    - `loadRemote('<slug>/…')` but doesn't declare a `widgets` edge;
    - declares a `css`/`widgets` edge it never actually uses (declared-but-unused)."""
    warns: list[str] = []
    names = [n for n, _ in enabled]
    metas = {n: _read_module_json(modules_dir, n) for n in names}
    slug_of = {n: _slug_of(n, metas[n]) for n in names}
    name_by_slug = {slug_of[n]: n for n in names}

    for n in names:
        src = _read_frontend_src(modules_dir, n)
        if not src:
            continue
        css_decl, widget_decl = set(), set()
        for edge in metas[n].get("dependsOn", []) or []:
            tgt, kinds = edge.get("module"), (edge.get("kinds") or [])
            if tgt in slug_of:
                if "css" in kinds:
                    css_decl.add(slug_of[tgt])
                if "widgets" in kinds:
                    widget_decl.add(slug_of[tgt])

        used_css, used_widget = set(), set()
        for other in names:
            if other == n:
                continue
            s = slug_of[other]
            if s in ("ideable", ""):
                continue
            if re.search(rf"(?<![\w-]){re.escape(s)}:{_CSS_VARIANTS}{_CSS_UTIL}", src):
                used_css.add(s)
            if re.search(rf"""loadRemote\(\s*['"]{re.escape(s)}/""", src):
                used_widget.add(s)

        for s in used_css - css_decl:
            tgt = name_by_slug[s]
            if tgt == HOST_MODULE:
                warns.append(f'module "{n}" uses "{s}:" CSS classes — prefer @ideable/ui shared widgets over host_app classes')
            else:
                warns.append(f'module "{n}" uses "{s}:" CSS classes but does not declare dependsOn {{module:"{tgt}", kinds:["css"]}}')
        for s in used_widget - widget_decl:
            warns.append(f'module "{n}" loadRemote("{s}/…") but does not declare dependsOn {{module:"{name_by_slug[s]}", kinds:["widgets"]}}')
        for s in css_decl - used_css:
            warns.append(f'module "{n}" declares a css dependsOn on "{name_by_slug[s]}" but uses no "{s}:" classes (declared-but-unused)')
        for s in widget_decl - used_widget:
            warns.append(f'module "{n}" declares a widgets dependsOn on "{name_by_slug[s]}" but never loadRemote("{s}/…") (declared-but-unused)')
    return warns


def _main(argv: list[str]) -> int:
    modules_dir = "modules"
    for i, a in enumerate(argv):
        if a == "--modules-dir" and i + 1 < len(argv):
            modules_dir = argv[i + 1]
    enabled = read_enabled_modules(modules_dir)
    if not enabled:
        print("No enabled modules found in modules/enabled.md — nothing to resolve.")
        return 0
    try:
        result = resolve(enabled, modules_dir)
    except ModuleDepError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for w in result["warnings"]:
        print("WARNING: " + w, file=sys.stderr)
    print("Resolved module order (providers first): " + " -> ".join(result["order"]))
    for mod in result["order"]:
        edges = result["edges"].get(mod, [])
        if edges:
            print(f"  {mod} dependsOn: {', '.join(edges)}")

    # Lints (warn-only): provides-vs-reality + cross-module dependency drift.
    lint = validate_provides(enabled, modules_dir) + drift_lint(enabled, modules_dir)
    for w in lint:
        print("LINT: " + w, file=sys.stderr)
    if not lint:
        print("Dependency lint: no issues (provides match reality; no undeclared/unused cross-module usage).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
