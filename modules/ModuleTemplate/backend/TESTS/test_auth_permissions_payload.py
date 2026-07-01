from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "SOURCES" / "app"


def test_auth_supports_permission_payload_variants() -> None:
    content = (APP_PATH / "auth.py").read_text(encoding="utf-8")
    assert "payload.get('permissions')" in content
    assert "payload.get('active_profile_permissions'" in content


def test_routers_support_server_table_contract() -> None:
    routers_dir = APP_PATH / "routers"
    router_files = [f for f in routers_dir.glob("*.py") if f.name != "__init__.py"]
    assert router_files, "No router files found in app/routers/"

    list_routers = [
        f for f in router_files
        if "skip: int" in f.read_text(encoding="utf-8")
    ]
    assert list_routers, "No routers with paginated list endpoints found"

    for router_path in list_routers:
        content = router_path.read_text(encoding="utf-8")
        assert "skip: int = 0" in content, f"{router_path.name}: missing skip param"
        assert "limit: int" in content, f"{router_path.name}: missing limit param"
        assert "sort_by: Optional[str] = None" in content, f"{router_path.name}: missing sort_by param"
        assert "sort_order: Optional[str] = None" in content, f"{router_path.name}: missing sort_order param"

    crud_content = (APP_PATH / "crud.py").read_text(encoding="utf-8")
    assert "query.offset(skip).limit(limit).all()" in crud_content, \
        "crud.py: missing offset/limit pagination pattern"
    assert "Invalid sort_by" in crud_content, "crud.py: missing sort_by validation"
    assert "Invalid sort_order" in crud_content, "crud.py: missing sort_order validation"
