from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "SOURCES" / "app"


def test_permissions_are_resolved_via_hostapp_not_read_from_the_token() -> None:
    """The token is thin: a remote module asks host_app what the caller may do.

    Reading permissions from claims would find none on a thin token and deny everything -- or,
    during a rolling upgrade, find a stale set and honour it. There is one source.
    """
    content = (APP_PATH / "auth.py").read_text(encoding="utf-8")
    assert "_get_permissions_from_claims" not in content, (
        "the claim arrays this read no longer exist in the token"
    )
    assert "def _resolve_permissions(" in content
    assert "HOSTAPP_API_URL" in content and "/api/me" in content

    body = content.split("def _resolve_permissions(")[1].split("\ndef ")[0]
    assert "authentik" not in body.lower(), (
        "resolution must not reach the identity plane on the request path"
    )


def test_a_resolution_failure_denies_and_says_it_could_not_decide() -> None:
    content = (APP_PATH / "auth.py").read_text(encoding="utf-8")
    body = content.split("def require_permission(")[1].split("\ndef ")[0]
    assert "PermissionResolutionError" in body
    assert "HTTP_503_SERVICE_UNAVAILABLE" in body, (
        "'we could not decide' is a different operational problem from 403's 'we decided no'"
    )


def test_an_unreachable_hostapp_denies_rather_than_widening_scope() -> None:
    """The cross-tenant permission widens a scope; failing to resolve it must never grant one.

    This used to be satisfied by keeping the caller's own tenants (which came from the token) and
    setting `read_all = False`. Tenancy now comes from host_app too, so an unresolvable request has
    no scope at all and is denied outright — strictly narrower than before, and for the same reason.
    Falling back would be worse than failing: the only value available to fall back to is a stale
    one, honoured after an administrator changed it.
    """
    content = (APP_PATH / "auth.py").read_text(encoding="utf-8")
    body = content.split("def require_tenant_scope(")[1].split("\ndef ")[0]
    assert "HTTP_503_SERVICE_UNAVAILABLE" in body, (
        "an unreachable host_app no longer denies the request; if the scope is defaulted or taken "
        "from a claim, an outage silently changes who can read what"
    )
    assert "CROSS_TENANT_READ_PERMISSION in resolved.permissions" in body, (
        "the cross-tenant widening is not read from the same resolution that produced the scope, "
        "so the two halves of one decision can disagree"
    )
    widening = body.index("CROSS_TENANT_READ_PERMISSION")
    denial = body.index("HTTP_403_FORBIDDEN")
    assert denial < widening, (
        "the widening is evaluated before the fail-closed gate; a caller with the cross-tenant "
        "permission and no tenant of its own must still be denied — the permission widens a scope, "
        "it does not conjure one"
    )


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
