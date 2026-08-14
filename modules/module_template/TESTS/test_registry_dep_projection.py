"""Contract test for the module-registry dependency projection (Phase 2 of the
module-dependency system). Force-synced.

`build_and_deploy._css_widget_deps_slugs` projects each module's declared `dependsOn`
edges (css/widgets kinds) into provider SLUGS carried in module-registry.json, which the
host_app frontend consumes to inject cross-module stylesheets / use widget remotes.
"""
import importlib.util
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUILD = PROJECT_ROOT / "scripts" / "common" / "build_and_deploy.py"


def _load():
    spec = importlib.util.spec_from_file_location("build_and_deploy", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b = _load()


def _emd(tmp: Path):
    def mk(name, slug, **fields):
        d = tmp / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "module.json").write_text(
            json.dumps({"name": name, "slug": slug, "role": "remote", **fields}), encoding="utf-8"
        )
        return (name, str(d), {"name": name, "slug": slug, "role": "remote", "displayName": name}, "local")

    return [
        mk("host_app", "hostapp", role="host"),
        mk("report_generator", "reportgen"),
        mk("styles_only", "stylesonly"),
        mk("SRA", "sra", dependsOn=[
            {"module": "report_generator", "kinds": ["api", "widgets"]},
            {"module": "styles_only", "kinds": ["css"]},
        ]),
    ]


def test_projection_maps_css_and_widget_kinds_to_provider_slugs(tmp_path: Path) -> None:
    proj = b._css_widget_deps_slugs(_emd(tmp_path))
    assert proj["SRA"]["cssDependsOn"] == ["stylesonly"], "css edge → provider slug"
    assert proj["SRA"]["widgetDependsOn"] == ["reportgen"], "widgets edge → provider slug"
    # api-only / no-dep modules project nothing.
    assert proj["report_generator"] == {"cssDependsOn": [], "widgetDependsOn": []}


def test_apply_projection_adds_only_nonempty_fields(tmp_path: Path) -> None:
    proj = b._css_widget_deps_slugs(_emd(tmp_path))
    sra = b._apply_dep_projection({"name": "sra"}, "SRA", proj)
    assert sra["cssDependsOn"] == ["stylesonly"] and sra["widgetDependsOn"] == ["reportgen"]
    # A module with no css/widgets deps gets neither key added.
    plain = b._apply_dep_projection({"name": "reportgen"}, "report_generator", proj)
    assert "cssDependsOn" not in plain and "widgetDependsOn" not in plain
