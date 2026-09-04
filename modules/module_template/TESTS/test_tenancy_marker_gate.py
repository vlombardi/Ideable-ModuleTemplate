"""This project's backends satisfy the tenancy-declaration gate.

The gate's OWN behaviour — that it fires on a model declaring nothing — is framework tooling, and is
tested in `scripts/TESTS/test_tenancy_marker_gate_tool.py`, which never ships. Those cases used to
live here, which meant they were force-synced into every remote module project and counted as that
module's `Cfg test` coverage while testing code the module may not modify — misreporting both, and
asking a remote maintainer to run a check they cannot act on.

What remains is the module's own statement: *my* backends declare their tenancy. That is the part a
remote maintainer can act on, and the only part that belongs in a force-synced module test
(`rules/testing-guidelines.md` § *What ships is tested here*).
"""
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GATE = PROJECT_ROOT / "scripts" / "common" / "check_tenancy_markers.py"
VALIDATOR = PROJECT_ROOT / "scripts" / "common" / "validate_modules.sh"


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_tenancy_markers", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


gate = _load_gate()


#: Every module in THIS project that has backend sources — discovered, never named.
#:
#: The two names used to be written out, and in a remote module project that produced a skip reading
#: "module_template has no backend sources in this checkout". True, and badly misleading: the module
#: there is called something else and DOES have backend sources, so the gate silently stopped being
#: exercised on the only code it protects. A skip is supposed to mean "not applicable here", not
#: "the lookup used the wrong name" (rules/testing-guidelines.md).
BACKENDS = sorted(
    (d.name, d / "backend" / "SOURCES" / "app")
    for d in (PROJECT_ROOT / "modules").iterdir()
    if (d / "backend" / "SOURCES" / "app").is_dir()
)


class TestThisProjectPasses:
    """The gate is wired in, and the real modules satisfy it."""

    def test_the_scan_finds_a_backend_to_check(self):
        """Otherwise the parametrised test below reports nothing and reads as a pass."""
        assert BACKENDS, (
            "no modules/*/backend/SOURCES/app found — this test would then assert nothing about "
            "the project while still reporting green"
        )

    @pytest.mark.parametrize("module,app_dir", BACKENDS, ids=[name for name, _ in BACKENDS])
    def test_the_enabled_modules_declare_their_tenancy(self, module, app_dir):
        assert gate.main([str(app_dir), "--module", module]) == 0

    def test_the_validator_actually_calls_the_gate(self):
        """A gate nothing invokes is a script, not a gate."""
        assert "check_tenancy_markers.py" in VALIDATOR.read_text(encoding="utf-8")
