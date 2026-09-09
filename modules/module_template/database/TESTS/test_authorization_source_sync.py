import re
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[2]
# The module authorization contract lives under config/ (mounted into the
# bootstrap container from ./config/authorization.yaml), not SPECS/.
AUTHORIZATION_SPEC_PATH = MODULE_ROOT / "config" / "authorization.yaml"


def _get_yaml_contract_text() -> str:
    return AUTHORIZATION_SPEC_PATH.read_text(encoding="utf-8")


def test_spec_authorization_exists() -> None:
    assert AUTHORIZATION_SPEC_PATH.exists(), "authorization.yaml not found in SPECS/"


def test_spec_authorization_documents_idempotency() -> None:
    content = _get_yaml_contract_text()
    # The bootstrap contract is idempotent: re-running must not duplicate
    # identities, roles, permissions, or mappings. This is documented in the
    # contract file.
    assert "idempotent" in content.lower(), \
        "authorization.yaml must document idempotent bootstrap behavior"


def test_spec_authorization_is_consumed_by_bootstrap_compose() -> None:
    compose_path = MODULE_ROOT / "docker-compose.yml"
    content = compose_path.read_text(encoding="utf-8")
    assert "./config/authorization.yaml:/module/authorization.yaml:ro" in content, \
        "docker-compose.yml must mount the module-level config authorization contract directly"


def test_spec_authorization_defines_entity_permissions() -> None:
    content = _get_yaml_contract_text()
    # The authorization contract defines entity permissions in the standard bare
    # <resource>:<action> scheme (the backend prepends the module prefix at runtime —
    # see ideable-framework-specs/auth-specs.md). Resource names are module-specific and
    # do NOT map 1:1 to table names (they may be pluralized or differently scoped — e.g.
    # SRA's `assets`/`assessment_types`), so assert the standard CRUD *actions* exist in
    # that scheme rather than a literal entity. Module-agnostic.
    for action in ("view", "edit", "menu_access"):
        assert re.search(rf"\w+:{action}\b", content), \
            f"authorization.yaml defines no <resource>:{action} permission (standard CRUD scheme)"
