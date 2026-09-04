"""Contract tests for the additive cross-module depends_on generator (Phase 1 deferred
sub-step of the module-dependency system). Force-synced to every remote.

The generator injects a provider's readiness gates into a dependent module's ROOT,
non-healthcheck services — reproducing the hand-authored pattern (so existing modules
produce an EMPTY override) while wiring newly-declared cross-module edges automatically.
"""
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GEN = PROJECT_ROOT / "scripts" / "common" / "compose_deps.py"

pytest.importorskip("yaml", reason="PyYAML required for compose parsing")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cd = _load(GEN)

PROVIDER = """
services:
  reportgen-database:
    image: postgres:16-alpine
    healthcheck: { test: ["CMD", "pg_isready"] }
  reportgen-backend:
    image: reportgen-backend:latest
    healthcheck: { test: ["CMD", "curl", "-f", "http://localhost/health"] }
    depends_on: { reportgen-database: { condition: service_healthy } }
"""

# Consumer with a bootstrap (root, no healthcheck), its own db (root, healthcheck), and a
# backend that chains off the bootstrap.
CONSUMER = """
services:
  sra-bootstrap:
    image: postgres:16-alpine
  sra-database:
    image: postgres:16-alpine
    healthcheck: { test: ["CMD", "pg_isready"] }
  sra-backend:
    image: sra-backend:latest
    depends_on: { sra-bootstrap: { condition: service_completed_successfully } }
"""


def test_generator_source_exists() -> None:
    assert GEN.is_file(), "scripts/common/compose_deps.py must exist (framework-owned)"


def test_injects_gates_into_root_nonhealthcheck_services_only() -> None:
    ms = {"reportgen": cd.load_services(PROVIDER), "SRA": cd.load_services(CONSUMER)}
    gates = {"reportgen": [("reportgen-backend", "service_healthy")], "SRA": []}
    edges = {"SRA": ["reportgen"], "reportgen": []}
    override = cd.compute_override(ms, edges, gates)
    # Injected into the root, no-healthcheck entry service…
    assert override.get("sra-bootstrap") == {"reportgen-backend": "service_healthy"}
    # …NOT into the module's own database (root but has a healthcheck)…
    assert "sra-database" not in override
    # …NOT into sra-backend (has an intra-module dependency → not a root).
    assert "sra-backend" not in override


def test_dedup_skips_already_declared_edges() -> None:
    consumer = """
services:
  sra-bootstrap:
    image: x
    depends_on: { reportgen-backend: { condition: service_healthy } }
"""
    ms = {"reportgen": cd.load_services(PROVIDER), "SRA": cd.load_services(consumer)}
    gates = {"reportgen": [("reportgen-backend", "service_healthy")]}
    override = cd.compute_override(ms, {"SRA": ["reportgen"]}, gates)
    assert override == {}, "an already-declared edge must not be duplicated"


def test_missing_gate_service_is_skipped() -> None:
    ms = {"SRA": cd.load_services(CONSUMER)}  # provider not present in the merged set
    gates = {"reportgen": [("reportgen-backend", "service_healthy")]}
    override = cd.compute_override(ms, {"SRA": ["reportgen"]}, gates)
    assert override == {}, "gate service absent from the merged set must be skipped"


def test_render_is_none_when_empty() -> None:
    assert cd.render_override({}) is None


def test_inject_into_module_compose_adds_fresh_depends_on() -> None:
    import yaml
    text = """services:
  sra-bootstrap:
    image: postgres:16-alpine
    command: ["sh", "-c", "echo hi"]
  sra-backend:
    image: x
    depends_on:
      sra-bootstrap:
        condition: service_completed_successfully
"""
    out = cd.inject_into_module_compose(text, {
        "sra-bootstrap": {"database": "service_healthy", "authentik-bootstrap": "service_completed_successfully"},
    })
    d = yaml.safe_load(out)
    dep = d["services"]["sra-bootstrap"]["depends_on"]
    assert dep["database"]["condition"] == "service_healthy"
    assert dep["authentik-bootstrap"]["condition"] == "service_completed_successfully"
    # untouched service preserved
    assert d["services"]["sra-backend"]["depends_on"]["sra-bootstrap"]["condition"] == "service_completed_successfully"
    # command preserved (formatting-preserving injection)
    assert d["services"]["sra-bootstrap"]["command"] == ["sh", "-c", "echo hi"]


def test_inject_into_module_compose_merges_and_dedups() -> None:
    import yaml
    text = """services:
  sra-bootstrap:
    image: x
    depends_on:
      database:
        condition: service_healthy
"""
    out = cd.inject_into_module_compose(text, {
        "sra-bootstrap": {"database": "service_healthy", "authentik-bootstrap": "service_completed_successfully"},
    })
    dep = yaml.safe_load(out)["services"]["sra-bootstrap"]["depends_on"]
    # existing database kept once (dedup), authentik-bootstrap merged in
    assert set(dep.keys()) == {"database", "authentik-bootstrap"}
    assert out.count("database:") == 1


def test_render_produces_valid_depends_on_yaml() -> None:
    import yaml
    text = cd.render_override({"sra-bootstrap": {"reportgen-backend": "service_healthy"}})
    data = yaml.safe_load(text)
    assert data["services"]["sra-bootstrap"]["depends_on"]["reportgen-backend"]["condition"] == "service_healthy"


def test_generator_runs_on_this_project() -> None:
    """Smoke on THIS checkout's real enabled set: generation runs (kind-filtered startup
    edges), the override is well-formed, and every generated edge maps a real consumer
    service to a gate service actually declared by some provider. Holds in the main repo
    (where module_template's bootstrap relies on generation) and in remotes alike."""
    import importlib.util as _il
    md_spec = _il.spec_from_file_location("module_deps", PROJECT_ROOT / "scripts" / "common" / "module_deps.py")
    md = _il.module_from_spec(md_spec); md_spec.loader.exec_module(md)

    modules_dir = PROJECT_ROOT / "modules"
    enabled = md.read_enabled_modules(str(modules_dir))
    if not enabled:
        pytest.skip("no enabled modules in this checkout")
    resolved = md.resolve(enabled, str(modules_dir))

    import json
    ms, gates = {}, {}
    for name, _mode in enabled:
        compose = modules_dir / name / "docker-compose.yml"
        if compose.is_file():
            ms[name] = cd.load_services(compose.read_text(encoding="utf-8"))
        mj = modules_dir / name / "module.json"
        meta = json.loads(mj.read_text(encoding="utf-8")) if mj.is_file() else {}
        gates[name] = cd.gates_of(meta)

    override = cd.compute_override(ms, md.startup_edges(resolved), gates)
    text = cd.render_override(override)
    if text is None:
        assert override == {}
        return
    import yaml
    parsed = yaml.safe_load(text)
    assert isinstance(parsed.get("services"), dict) and parsed["services"]
    declared_gates = {svc for gl in gates.values() for svc, _ in gl}
    all_services = {s for svcs in ms.values() for s in svcs}
    for consumer, spec in parsed["services"].items():
        assert consumer in all_services, f"generated consumer {consumer} is not a real service"
        for gate in spec["depends_on"]:
            assert gate in declared_gates, f"gate {gate} not declared by any provider"
            assert gate in all_services, f"gate {gate} is not a real service"
