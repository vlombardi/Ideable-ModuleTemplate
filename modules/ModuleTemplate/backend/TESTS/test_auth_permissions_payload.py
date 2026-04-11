from pathlib import Path


def test_moduletemplate_auth_supports_hostapp_permissions_payload_variants() -> None:
    auth_path = (
        Path(__file__).resolve().parents[1]
        / "SOURCES"
        / "app"
        / "auth.py"
    )

    content = auth_path.read_text(encoding="utf-8")
    assert "payload.get('permissions')" in content
    assert "payload.get('active_profile_permissions'" in content


def test_moduletemplate_items_backend_supports_server_table_contract() -> None:
    base_path = Path(__file__).resolve().parents[1] / "SOURCES" / "app"

    router_content = (base_path / "routers" / "items.py").read_text(encoding="utf-8")
    assert "response_model=schemas.TemplateItemsPage" in router_content
    assert "skip: int = 0" in router_content
    assert "limit: int = 100" in router_content
    assert "sort_by: Optional[str] = None" in router_content
    assert "sort_order: Optional[str] = None" in router_content

    crud_content = (base_path / "crud.py").read_text(encoding="utf-8")
    assert "def list_items(" in crud_content
    assert "query.offset(skip).limit(limit).all()" in crud_content
    assert "Invalid sort_by" in crud_content
    assert "Invalid sort_order" in crud_content
