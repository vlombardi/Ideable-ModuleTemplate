"""The tenancy contract's three names must agree — asserted where a checkout can assert it.

The entity named by `<entity>:read_all_tenants` is referred to by three naming systems, and
`test_tenant_isolation.py` has to line them up before it can exercise anything:

    permission entity  <-  config/authorization.yaml
    collection route   <-  the running backend's /openapi.json
    table              <-  backend/SOURCES/app/models.py __tablename__

Two of the three are static facts about files in the checkout. **This file asserts those two**, and
it is separate from the isolation suite for one reason: every test in that suite is gated on a live
stack (its `purge_synthetic_audit_residue` fixture is session-scoped, autouse, and depends on
`stack`), so a checkout with nothing running skips the whole file. Putting this assertion there
would make the one report a module needs available only in the situation where it is least urgent.

The failure this replaces: the suite derived the entity at module scope and asserted on the way, so
a naming disagreement was a **collection error** — the file could not be imported, every test in it
went red at once, and the single sentence naming which of the three names disagreed was buried under
36 failures that said nothing. A reported module hit exactly that, in a suite about tenancy.

Stack-free by construction: it reads the sibling's resolution and two files in the checkout. It
contacts nothing. (The route half cannot be checked without a running backend and stays in the
isolation suite, which now reports it as one readable failure naming all three names.)

Force-synced and slug-free: everything comes from what the module itself authors.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_SUITE = _TESTS / "test_tenant_isolation.py"


def _isolation_suite():
    """The isolation suite's module object, imported for its resolution alone.

    Imported rather than re-implemented: a second copy of the derivation would be free to disagree
    with the one the suite actually uses, and then this file would certify a contract the suite
    rejects. The import runs the resolution — which is pure, reads two files, and by design cannot
    raise (see `_ContractUnresolved` there).
    """
    name = "ideable_tenancy_isolation_suite"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SUITE)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec (dataclasses and `@` decorators resolve annotations through
    # `sys.modules[cls.__module__]`), and removed again if exec fails. Leaving a half-executed
    # module cached would make every test below raise AttributeError on the exact regression this
    # file exists to detect — reproducing, in miniature, the "buried under N meaningless failures"
    # shape being fixed.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _suite_or_skip():
    """The suite, or a skip — so exactly one test reports an import failure.

    Without this, an import failure fails all five tests here with `AttributeError`, which is the
    same unreadable shape as the collection error this file was written to replace.
    """
    try:
        return _isolation_suite()
    except Exception:  # noqa: BLE001 — reported by the dedicated test below, not by every test
        pytest.skip("the isolation suite could not be imported; the test above is the one that "
                    "reports it")


def test_the_isolation_suite_can_be_imported_at_all():
    """The property that makes every other report in that file readable.

    An import failure here IS the old defect, restored: it would mean the derivation raises at
    module scope again, and a naming disagreement would once more arrive as a collection error over
    the whole tenancy suite instead of as one sentence.
    """
    try:
        _isolation_suite()
    except Exception as exc:  # noqa: BLE001 — an import failure is exactly what is being detected
        pytest.fail(
            f"{_SUITE.name} could not be imported: {type(exc).__name__}: {exc}\n"
            f"Its entity resolution must capture a problem rather than raise it. While it raised, "
            f"a naming disagreement was reported as a collection error over every test in the file."
        )


def test_the_permission_entity_and_the_table_agree():
    """The contract, as one failure naming every name it looked at."""
    suite = _suite_or_skip()
    assert suite.CONTRACT_PROBLEM is None, suite.CONTRACT_PROBLEM


def test_the_resolved_names_are_all_present():
    """A resolution that "succeeded" while leaving a placeholder behind would certify nothing."""
    suite = _suite_or_skip()
    if suite.CONTRACT_PROBLEM:
        pytest.skip("the contract does not resolve; the test above is the one that reports it")
    resolved = {
        "entity": suite._ENTITY,
        "permission": suite.CROSS_TENANT_PERMISSION,
        "cross-tenant profile": suite.CROSS_TENANT_PROFILE,
        "entity-admin profile": suite.ENTITY_ADMIN_PROFILE,
        "table": suite.ENTITY_TABLE,
        "version table": suite.ENTITY_VERSION_TABLE,
    }
    placeholders = sorted(k for k, v in resolved.items() if not v or v == suite._UNRESOLVED)
    assert not placeholders, (
        f"the contract reported no problem and yet {placeholders} are unresolved — every query and "
        f"every persona in the isolation suite would then be built from a placeholder"
    )
    assert resolved["version table"] == f"{resolved['table']}_version", (
        f"the Continuum version table is not derived from the entity table: "
        f"{resolved['version table']!r} vs {resolved['table']!r}"
    )


def test_the_permission_is_qualified_with_this_modules_slug():
    """The token carries `<slug>.<entity>:read_all_tenants`; the file stores it unprefixed."""
    suite = _suite_or_skip()
    if suite.CONTRACT_PROBLEM:
        pytest.skip("the contract does not resolve; the test above is the one that reports it")
    assert suite.CROSS_TENANT_PERMISSION.endswith(f".{suite._ENTITY}:read_all_tenants"), (
        f"{suite.CROSS_TENANT_PERMISSION!r} is not `<slug>.{suite._ENTITY}:read_all_tenants`, so "
        f"the suite would look for a permission no bootstrap grants"
    )


def test_a_declared_mapping_is_honoured_when_the_module_states_one():
    """The escape hatch has to work, or a module whose names cannot match has no route out.

    Requiring one token to be the permission prefix, the collection route segment and the table
    name is a coupling the framework does not impose — kebab-plural routes over snake-singular
    tables is ordinary REST. When a module declares the mapping, that declaration must be what is
    used; `module_template` declares none and gets the identity convention.
    """
    suite = _suite_or_skip()
    declared = suite._declared_entity_mapping()
    if not declared:
        pytest.skip("this module relies on the default convention, which the tests above check")
    if suite.CONTRACT_PROBLEM:
        pytest.skip("the contract does not resolve; the test above is the one that reports it")
    if declared.get("table"):
        assert suite.ENTITY_TABLE == declared["table"], (
            f"module.json declares crossTenantEntity.table = {declared['table']!r} and the suite "
            f"resolved {suite.ENTITY_TABLE!r} — the declaration is being ignored"
        )
