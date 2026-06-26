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
    / "shared-ui-specs.md"
)
MODULE_TEMPLATE_BASE_SPECS = (
    Path(__file__).resolve().parents[1]
    / "SPECS"
    / "base_specs.md"
)
HOSTAPP_INTEGRATION_SPECS = (
    Path(__file__).resolve().parents[3]
    / "HostApp"
    / "SPECS"
    / "module-integration-specs.md"
)
MAIN_TSX = (
    Path(__file__).resolve().parents[1]
    / "SOURCES"
    / "src"
    / "main.tsx"
)
INDEX_CSS = (
    Path(__file__).resolve().parents[1]
    / "SOURCES"
    / "src"
    / "index.css"
)


def test_module_manifest_routes_are_module_local() -> None:
    content = MODULE_MANIFEST.read_text(encoding="utf-8")

    assert "path: '/items'" in content
    assert "path: '/template/items'" not in content


def test_module_manifest_menu_hrefs_are_hostapp_absolute() -> None:
    content = MODULE_MANIFEST.read_text(encoding="utf-8")

    assert "href: '/template/items'" in content


def test_moduletemplate_specs_define_remote_lf_contract() -> None:
    ui_specs = MODULE_TEMPLATE_UI_SPECS.read_text(encoding="utf-8")
    base_specs = MODULE_TEMPLATE_BASE_SPECS.read_text(encoding="utf-8")

    assert "Default behavior must match HostApp L&F and widget interaction patterns." in ui_specs
    assert "Module-specific L&F customizations are opt-in and must be scoped to the module root only." in ui_specs
    assert "Remote pages must not mutate HostApp global selectors (`html`, `body`, universal `*`)." in ui_specs

    assert "ModuleTemplate is the canonical, always-updated compatibility reference" in base_specs
    assert "Module developers should be able to rely on ModuleTemplate alone" in base_specs
    assert "Default mode (mandatory): ModuleTemplate pages inherit HostApp visual tokens" in base_specs


def test_hostapp_specs_define_moduletemplate_discoverability_contract() -> None:
    hostapp_specs = HOSTAPP_INTEGRATION_SPECS.read_text(encoding="utf-8")

    assert "## 6.1) Canonical Reference Module" in hostapp_specs
    assert "`modules/ModuleTemplate/` is the canonical, always-updated reference implementation" in hostapp_specs
    assert "## 6.2) UI/L&F Discoverability Contract" in hostapp_specs
    assert "HostApp compatibility must be discoverable through versioned artifacts" in hostapp_specs


def test_moduletemplate_runtime_lf_mode_switch_contract() -> None:
    main_content = MAIN_TSX.read_text(encoding="utf-8")
    css_content = INDEX_CSS.read_text(encoding="utf-8")

    assert "VITE_TEMPLATE_LF_MODE" in main_content
    assert "=== 'module' ? 'module' : 'hostapp'" in main_content
    assert "data-lf={lfMode}" in main_content

    assert ".template-scope[data-lf='hostapp']" in css_content
    assert ".template-scope[data-lf='module']" in css_content
    assert "--template-module-background" in css_content
