#!/usr/bin/env python3
"""Generate additive cross-module compose ``depends_on`` from declared module dependencies.

Phase 1 (deferred sub-step) of the module-dependency system. Given the resolved dependency
edges (module A dependsOn module B) and each provider's declared readiness ``gates``
(``module.json`` ``provides.gates``), emit an ADDITIVE docker-compose override that makes
each dependent module's root entry services wait for the provider's gate services.

Safety constraints:
- ADDITIVE ONLY, via a separate override compose merged last — this never mutates or
  re-dumps the hand-authored module composes, so comments, ``$$`` escapes, heredoc command
  blocks and sync markers are preserved.
- Injects only into a dependent's ROOT services (no intra-module ``depends_on``) that have
  NO healthcheck of their own — i.e. work-entry services like bootstrap/backend, not the
  module's own infra database. This reproduces the hand-authored pattern (only the bootstrap
  waits on host_app), so existing modules produce an EMPTY override (no change).
- Dedups against ``depends_on`` already declared in the base compose; guards that both the
  consumer service and the gate service exist in the merged set. Acyclic by construction
  (edges are acyclic; host_app depends on nothing).
"""
from __future__ import annotations

import json
import os
import sys

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def load_services(compose_text: str) -> dict:
    """Parse a compose file's services into
    ``{name: {deps: set, existing: {dep: condition}, healthcheck: bool}}``."""
    if yaml is None:
        return {}
    data = yaml.safe_load(compose_text) or {}
    services = data.get("services") or {}
    out: dict = {}
    for name, d in services.items():
        if not isinstance(d, dict):
            continue
        dep = d.get("depends_on")
        existing: dict = {}
        if isinstance(dep, dict):
            for k, v in dep.items():
                existing[k] = v.get("condition") if isinstance(v, dict) else None
        elif isinstance(dep, list):
            for k in dep:
                if isinstance(k, str):
                    existing[k] = None
        out[name] = {
            "deps": set(existing.keys()),
            "existing": existing,
            "healthcheck": "healthcheck" in d,
        }
    return out


def gates_of(module_meta: dict) -> list:
    """Readiness gates a module offers consumers: ``[(service, condition), ...]``."""
    prov = (module_meta or {}).get("provides") or {}
    out = []
    for g in prov.get("gates") or []:
        if isinstance(g, dict) and g.get("service"):
            out.append((g["service"], g.get("condition") or "service_started"))
    return out


def compute_override(module_services: dict, edges: dict, gates_by_module: dict) -> dict:
    """Return ``{consumer_service: {gate_service: condition}}`` to add. Pure function."""
    all_services: set = set()
    for svcs in module_services.values():
        all_services |= set(svcs.keys())

    override: dict = {}
    for module, svcs in module_services.items():
        own = set(svcs.keys())
        # Root entry services: no intra-module dependency AND no own healthcheck.
        roots = [
            s for s, info in svcs.items()
            if not (info["deps"] & own) and not info["healthcheck"]
        ]
        for provider in edges.get(module, []):
            for gate_svc, cond in gates_by_module.get(provider, []):
                if gate_svc not in all_services:
                    continue  # gate service not present in the merged set — skip
                for s in roots:
                    if s == gate_svc or gate_svc in svcs[s]["existing"]:
                        continue  # self-ref or already declared → dedup
                    override.setdefault(s, {})[gate_svc] = cond
    return override


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def inject_into_module_compose(compose_text: str, service_gates: dict) -> str:
    """Inject cross-module `depends_on` entries into specific services of a *deployed*
    module compose, preserving surrounding formatting (comments, `$$` escapes, heredocs).

    ``service_gates``: ``{service_name: {gate_service: condition}}``. Only adds gates not
    already declared for that service; merges into an existing ``depends_on:`` block or
    creates one. This is injected into the per-module deployed compose (not a separate
    override) so BOTH the build-time merge (build_and_deploy) and the runtime merge
    (create-merged-configuration.sh) — which re-merges per-module composes and is override
    file-unaware — preserve the generated ordering.
    """
    if not service_gates:
        return compose_text
    lines = compose_text.splitlines(keepends=True)
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        is_service_header = (
            _indent_of(line) == 2 and s.endswith(":") and not s.startswith("#") and not s.startswith("-")
        )
        if is_service_header and s[:-1] in service_gates:
            svc = s[:-1]
            gates = dict(service_gates[svc])
            out.append(line)
            i += 1
            # Body = lines until the next indent<=2 non-blank line.
            body_start = i
            while i < n and not (lines[i].strip() and _indent_of(lines[i]) <= 2):
                i += 1
            body = lines[body_start:i]
            dep_idx = next(
                (k for k, bl in enumerate(body) if _indent_of(bl) == 4 and bl.strip() == "depends_on:"),
                None,
            )
            if dep_idx is not None:
                existing = set()
                k = dep_idx + 1
                while k < len(body):
                    bl = body[k]
                    if bl.strip() and _indent_of(bl) <= 4:
                        break
                    if _indent_of(bl) == 6 and bl.strip().endswith(":"):
                        existing.add(bl.strip()[:-1])
                    k += 1
                add = []
                for g, cond in gates.items():
                    if g in existing:
                        continue
                    add += [f"      {g}:\n", f"        condition: {cond}\n"]
                body = body[: dep_idx + 1] + add + body[dep_idx + 1:]
            else:
                add = ["    depends_on:\n"]
                for g, cond in gates.items():
                    add += [f"      {g}:\n", f"        condition: {cond}\n"]
                body = add + body
            out.extend(body)
            continue
        out.append(line)
        i += 1
    return "".join(out)


def render_override(override: dict) -> str | None:
    """Render the override as compose YAML text, or ``None`` when there is nothing to add."""
    if not override or yaml is None:
        return None
    services = {
        s: {"depends_on": {g: {"condition": c} for g, c in sorted(gates.items())}}
        for s, gates in sorted(override.items())
    }
    header = (
        "# GENERATED — cross-module depends_on derived from module.json `dependsOn` +\n"
        "# providers' `provides.gates`. Do not edit; regenerated by build_and_deploy.\n"
        "# Additive override (merged last) that reinforces cross-module startup ordering.\n"
    )
    return header + yaml.safe_dump({"services": services}, sort_keys=True, default_flow_style=False)


# ── CLI dry-run ─────────────────────────────────────────────────────────────────────
def _main(argv: list[str]) -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import module_deps  # sibling

    modules_dir = "modules"
    for i, a in enumerate(argv):
        if a == "--modules-dir" and i + 1 < len(argv):
            modules_dir = argv[i + 1]

    enabled = module_deps.read_enabled_modules(modules_dir)
    if not enabled:
        print("No enabled modules — nothing to generate.")
        return 0
    resolved = module_deps.resolve(enabled, modules_dir)

    module_services = {}
    gates_by_module = {}
    for name, _mode in enabled:
        compose = os.path.join(modules_dir, name, "docker-compose.yml")
        if os.path.isfile(compose):
            with open(compose, encoding="utf-8") as f:
                module_services[name] = load_services(f.read())
        mj = os.path.join(modules_dir, name, "module.json")
        meta = json.load(open(mj, encoding="utf-8")) if os.path.isfile(mj) else {}
        gates_by_module[name] = gates_of(meta)

    override = compute_override(module_services, module_deps.startup_edges(resolved), gates_by_module)
    text = render_override(override)
    if not text:
        print("No cross-module depends_on to generate (all declared edges already satisfied).")
        return 0
    n = sum(len(v) for v in override.values())
    print(f"Would generate {n} cross-module depends_on edge(s):\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
