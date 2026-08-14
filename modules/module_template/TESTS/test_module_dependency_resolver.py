"""Contract tests for the inter-module dependency resolver (Phase 1 of the
module-dependency system). Force-synced to every remote.

Covers the resolver's guarantees: providers-first topological order, implicit host_app
dependency, hard-error on a missing required prerequisite, graceful skip when the edge is
optional, capability (`provides`) checking, and cycle detection — plus a smoke check that
THIS project's actual enabled set resolves.
"""
import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]          # repo root
RESOLVER = PROJECT_ROOT / "scripts" / "common" / "module_deps.py"


def _load_resolver():
    spec = importlib.util.spec_from_file_location("module_deps", RESOLVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


md = _load_resolver()


def _mk(modules_dir: Path, name: str, **fields) -> None:
    d = modules_dir / name
    d.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "slug": name.lower().replace("_", "")}
    payload.update(fields)
    (d / "module.json").write_text(json.dumps(payload), encoding="utf-8")


def test_resolver_source_exists() -> None:
    assert RESOLVER.is_file(), "scripts/common/module_deps.py must exist (framework-owned)"


def test_providers_ordered_before_consumers_and_host_first(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", frontendPort=3000, backendPort=8001)
    _mk(tmp_path, "report_generator", role="remote", backendPort=8003)      # provider
    _mk(tmp_path, "SRA", role="remote", frontendPort=3001, backendPort=8002,
        dependsOn=[{"module": "report_generator", "kinds": ["api"]}])        # consumer
    res = md.resolve([("host_app", "remote"), ("SRA", "local"), ("report_generator", "local")], str(tmp_path))
    order = res["order"]
    assert order[0] == "host_app", "host_app (implicit universal dep) must come first"
    assert order.index("report_generator") < order.index("SRA"), "provider before consumer"
    # implicit host_app edge is injected for every non-host module
    assert "host_app" in res["edges"]["SRA"] and "host_app" in res["edges"]["report_generator"]


def test_startup_edges_exclude_css_and_widgets_only(tmp_path: Path) -> None:
    """Container start-order gating keeps runtime/api/data edges (and the implicit host_app
    edge) but drops css/widgets-only edges (those are runtime-frontend, Phase 2)."""
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "styles_only", role="remote", frontendPort=3005)             # provides css
    _mk(tmp_path, "report_generator", role="remote", backendPort=8003)         # provides api
    _mk(tmp_path, "SRA", role="remote", frontendPort=3001, backendPort=8002,
        dependsOn=[
            {"module": "report_generator", "kinds": ["api"]},
            {"module": "styles_only", "kinds": ["css"]},
        ])
    res = md.resolve(
        [("host_app", "remote"), ("SRA", "local"),
         ("report_generator", "local"), ("styles_only", "local")],
        str(tmp_path),
    )
    se = md.startup_edges(res)
    assert "report_generator" in se["SRA"], "api edge must gate startup"
    assert "host_app" in se["SRA"], "implicit host_app edge must gate startup"
    assert "styles_only" not in se["SRA"], "a css-only edge must NOT gate startup"
    # …but the css edge is still a real dependency for build order / topo.
    assert "styles_only" in res["edges"]["SRA"]
    assert res["order"].index("styles_only") < res["order"].index("SRA")


def test_missing_required_target_is_hard_error(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "SRA", role="remote", backendPort=8002,
        dependsOn=[{"module": "report_generator", "kinds": ["api"]}])
    with pytest.raises(md.ModuleDepError) as exc:
        md.resolve([("host_app", "remote"), ("SRA", "local")], str(tmp_path))
    assert "report_generator" in str(exc.value) and "not enabled" in str(exc.value)


def test_optional_missing_target_is_skipped_with_warning(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "SRA", role="remote", backendPort=8002,
        dependsOn=[{"module": "report_generator", "kinds": ["api"], "optional": True}])
    res = md.resolve([("host_app", "remote"), ("SRA", "local")], str(tmp_path))   # no raise
    assert any("optional dependency skipped" in w for w in res["warnings"])
    assert "report_generator" not in res["edges"]["SRA"]


def test_capability_not_provided_is_error(tmp_path: Path) -> None:
    # provider has no frontend → provides.css defaults to False → css dep must fail.
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "backend_only", role="remote", backendPort=8003)            # no frontendPort
    _mk(tmp_path, "SRA", role="remote", frontendPort=3001,
        dependsOn=[{"module": "backend_only", "kinds": ["css"]}])
    with pytest.raises(md.ModuleDepError) as exc:
        md.resolve([("host_app", "remote"), ("SRA", "local"), ("backend_only", "local")], str(tmp_path))
    assert "does not provide" in str(exc.value)


def test_cycle_is_detected(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "A", role="remote", backendPort=8002, dependsOn=[{"module": "B", "kinds": ["api"]}])
    _mk(tmp_path, "B", role="remote", backendPort=8003, dependsOn=[{"module": "A", "kinds": ["api"]}])
    with pytest.raises(md.ModuleDepError) as exc:
        md.resolve([("host_app", "remote"), ("A", "local"), ("B", "local")], str(tmp_path))
    assert "cycle" in str(exc.value).lower()


def test_validate_provides_flags_api_without_backend_and_missing_widget(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "ghost_api", role="remote", provides={"api": True})  # no backend, no port
    wmod = tmp_path / "wmod" / "frontend" / "SOURCES"
    wmod.mkdir(parents=True)
    (tmp_path / "wmod" / "module.json").write_text(
        json.dumps({"name": "wmod", "slug": "wmod", "role": "remote", "provides": {"widgets": ["Foo"]}}),
        encoding="utf-8",
    )
    (wmod / "rsbuild.config.ts").write_text("exposes: { './moduleManifest': './src/moduleManifest.ts' }", encoding="utf-8")
    warns = "\n".join(md.validate_provides(
        [("host_app", "remote"), ("ghost_api", "local"), ("wmod", "local")], str(tmp_path)))
    assert "ghost_api" in warns and "provides.api" in warns
    assert "wmod" in warns and "Foo" in warns


def _mk_frontend(tmp_path: Path, name: str, slug: str, page_src: str, **fields) -> None:
    src = tmp_path / name / "frontend" / "SOURCES" / "src"
    src.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "slug": slug, "role": "remote"}
    payload.update(fields)
    (tmp_path / name / "module.json").write_text(json.dumps(payload), encoding="utf-8")
    (src / "Page.tsx").write_text(page_src, encoding="utf-8")


def test_drift_lint_undeclared_css_usage(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "sra", slug="sra", frontendPort=3002)
    # uses sra: CSS classes AND an sra: event name; declares no dependsOn.
    _mk_frontend(tmp_path, "app", "app",
                 "const c = 'sra:bg-accent sra:flex'\nwindow.addEventListener('sra:thing-changed', x)\n")
    warns = md.drift_lint([("host_app", "remote"), ("sra", "local"), ("app", "local")], str(tmp_path))
    joined = "\n".join(warns)
    assert 'uses "sra:" CSS classes' in joined and 'kinds:["css"]' in joined, joined
    # the event-name occurrence must NOT itself produce a spurious finding
    assert 'sra:thing-changed' not in joined


def test_drift_lint_declared_but_unused(tmp_path: Path) -> None:
    _mk(tmp_path, "host_app", role="host", backendPort=8001)
    _mk(tmp_path, "sra", slug="sra", frontendPort=3002)
    _mk_frontend(tmp_path, "app", "app", "const c = 'app:bg-accent'\n",
                 dependsOn=[{"module": "sra", "kinds": ["css"]}])
    warns = md.drift_lint([("host_app", "remote"), ("sra", "local"), ("app", "local")], str(tmp_path))
    assert any("declared-but-unused" in w for w in warns), warns


def test_this_project_enabled_set_resolves() -> None:
    """Smoke: the real modules/enabled.md for this checkout must resolve (acyclic +
    every required prerequisite enabled and providing its kinds)."""
    enabled = md.read_enabled_modules(str(PROJECT_ROOT / "modules"))
    if not enabled:
        pytest.skip("no enabled modules in this checkout")
    res = md.resolve(enabled, str(PROJECT_ROOT / "modules"))
    assert res["order"], "resolver returned an empty order"
    if any(n == "host_app" for n, _ in enabled):
        assert res["order"][0] == "host_app"
