import re
from pathlib import Path


MODULE_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "SOURCES"
    / "src"
    / "moduleManifest.ts"
)
MODULE_TEMPLATE_UI_SPECS = (
    Path(__file__).resolve().parents[1]
    / "SPECS"
    / "ideable-framework-specs"
    / "shared-ui-specs.md"
)
MODULE_TEMPLATE_BASE_SPECS = (
    Path(__file__).resolve().parents[1]
    / "SPECS"
    / "ideable-framework-specs"
    / "base_specs.md"
)
HOSTAPP_INTEGRATION_SPECS = (
    Path(__file__).resolve().parents[2]
    / "SPECS"
    / "ideable-framework-specs"
    / "module-integration-specs.md"
)
SRC_DIR = Path(__file__).resolve().parents[1] / "SOURCES" / "src"
INDEX_CSS = SRC_DIR / "index.css"


def _module_slug() -> str:
    """The module's slug (e.g. 'template'), from its own manifest. Contract assertions
    are parameterized by this so they hold for any module, not just module_template."""
    match = re.search(r"slug:\s*['\"]([^'\"]+)['\"]", MODULE_MANIFEST.read_text(encoding="utf-8"))
    assert match, "moduleManifest.ts must define a slug"
    return match.group(1)


def _entry_content() -> str:
    """Content of the app entry that carries the runtime L&F-mode switch.

    With the Module Federation async-boundary entry, main.tsx only does
    ``import('./bootstrap')`` and the App (VITE_<SLUG>_LF_MODE / data-lf) lives in
    bootstrap.tsx; without the split it is in main.tsx. Prefer bootstrap.tsx.
    """
    bootstrap = SRC_DIR / "bootstrap.tsx"
    entry = bootstrap if bootstrap.exists() else SRC_DIR / "main.tsx"
    return entry.read_text(encoding="utf-8")


def test_module_manifest_routes_are_module_local() -> None:
    content = MODULE_MANIFEST.read_text(encoding="utf-8")
    slug = _module_slug()

    # routes[].path must be module-LOCAL (e.g. '/items'), never host-absolute
    # ('/<slug>/items') — host_app composes basePath + route.
    paths = re.findall(r"path:\s*['\"]([^'\"]+)['\"]", content)
    assert paths, "moduleManifest.ts must define at least one route path"
    for path in paths:
        assert not path.startswith(f"/{slug}/"), \
            f"route path {path!r} must be module-local, not host-absolute (/{slug}/...)"


def test_module_manifest_menu_hrefs_are_hostapp_absolute() -> None:
    content = MODULE_MANIFEST.read_text(encoding="utf-8")
    slug = _module_slug()

    # menuItems[].href must be host-ABSOLUTE (/<slug>/...) so host_app routes to it.
    hrefs = re.findall(r"href:\s*['\"]([^'\"]+)['\"]", content)
    assert hrefs, "moduleManifest.ts must define at least one menu href"
    for href in hrefs:
        assert href.startswith(f"/{slug}/"), \
            f"menu href {href!r} must be host-absolute (/{slug}/...)"


def test_moduletemplate_specs_define_remote_lf_contract() -> None:
    ui_specs = MODULE_TEMPLATE_UI_SPECS.read_text(encoding="utf-8")
    base_specs = MODULE_TEMPLATE_BASE_SPECS.read_text(encoding="utf-8")

    assert "Default behavior must match host_app L&F and widget interaction patterns." in ui_specs
    assert "Module-specific L&F customizations are opt-in and must be scoped to the module root only." in ui_specs
    assert "Remote pages must not mutate host_app global selectors (`html`, `body`, universal `*`)." in ui_specs

    assert "module_template is the canonical, always-updated compatibility reference" in base_specs
    assert "Module developers should be able to rely on module_template alone" in base_specs
    assert "Default mode (mandatory): module_template pages inherit host_app visual tokens" in base_specs


def test_hostapp_specs_define_moduletemplate_discoverability_contract() -> None:
    hostapp_specs = HOSTAPP_INTEGRATION_SPECS.read_text(encoding="utf-8")

    assert "## 6.1) Canonical Reference Module" in hostapp_specs
    assert "`modules/module_template/` is the canonical, always-updated reference implementation" in hostapp_specs
    assert "## 6.2) Validation Discoverability Contract" in hostapp_specs
    assert "validation compatibility must be discoverable through versioned artifacts" in hostapp_specs


def test_moduletemplate_runtime_lf_mode_switch_contract() -> None:
    slug = _module_slug()
    main_content = _entry_content()
    css_content = INDEX_CSS.read_text(encoding="utf-8")

    # LF-mode switch + scope class + background token are all slug-based, so parameterize.
    assert f"VITE_{slug.upper()}_LF_MODE" in main_content
    assert "=== 'module' ? 'module' : 'hostapp'" in main_content
    assert "data-lf={lfMode}" in main_content

    assert f".{slug}-scope[data-lf='hostapp']" in css_content
    assert f".{slug}-scope[data-lf='module']" in css_content
    assert f"--{slug}-module-background" in css_content
