"""The bootstrap contract: database → migrations → seed → backend.

Every module with a database runs the same three steps in the same order, each owning exactly one
thing: migrations own DDL, the seed owns rows, the backend serves traffic once both have finished.

The seed step used to be guarded by the `module_bootstrap_execution` ledger. That guard is gone:
seed.sql must be idempotent, so a "did this already run?" check buys nothing while costing an
order-dependent trap — a ledger key recorded by an earlier release once stopped a block from
re-running, and `module_runtime_meta` was absent at deploy time as a result.

The ledger table itself stays, reserved for scripts that genuinely cannot be re-run.

See modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md.
"""
import json
import re
from pathlib import Path

import yaml

_MODULE = Path(__file__).resolve().parents[1]
_COMPOSE = yaml.safe_load((_MODULE / "docker-compose.yml").read_text(encoding="utf-8"))
_SERVICES = _COMPOSE.get("services", {})

# The service names are BUILT from this module's own slug, never written out.
#
# This file is copied byte-for-byte into every remote module project, where the module's slug is not
# `template` — so looking a service up under that name raised KeyError there, and seven of these
# assertions failed on a module that had done nothing wrong. `module.json` is the one
# answer that travels with the module and cannot be shadowed by an ambiguous `$MODULE_SLUG`, which
# is why `backend/TESTS/conftest.py` already reads it.
_SLUG = json.loads((_MODULE / "module.json").read_text(encoding="utf-8"))["slug"]
BOOTSTRAP = f"{_SLUG}-bootstrap"
MIGRATIONS = f"{_SLUG}-migrations"
BACKEND = f"{_SLUG}-backend"

for _expected in (BOOTSTRAP, MIGRATIONS, BACKEND):
    assert _expected in _SERVICES, (
        f"{_MODULE.name}/docker-compose.yml declares no {_expected!r} service. Every module's "
        f"bootstrap chain is named after its slug ({_SLUG!r}, from module.json); if this module "
        f"names its services differently, the deploy tooling will not find them either."
    )


class TestOrdering:

    def test_seed_waits_for_the_migrations(self):
        """The seed inserts into tables the migrations create."""
        assert MIGRATIONS in (_SERVICES[BOOTSTRAP].get("depends_on") or {})

    def test_backend_waits_for_the_seed(self):
        """A backend that starts before the seed can serve a functionally incomplete system."""
        assert BOOTSTRAP in (_SERVICES[BACKEND].get("depends_on") or {})

    def test_one_shot_jobs_never_restart(self):
        """A restarting one-shot can never satisfy `service_completed_successfully`."""
        for name in (MIGRATIONS, BOOTSTRAP):
            assert _SERVICES[name].get("restart") == "no", f"{name} may restart"


class TestSeedOwnsRowsOnly:

    def test_seed_job_applies_the_mounted_file(self):
        """Mounted, not baked: a deployment must be able to customise initial data."""
        volumes = _SERVICES[BOOTSTRAP].get("volumes") or []
        assert any("seed.sql:/module/seed.sql" in str(v) for v in volumes)

    def test_seed_job_contains_no_ddl(self):
        command = " ".join(str(c) for c in (_SERVICES[BOOTSTRAP].get("command") or []))
        for ddl in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE"):
            assert ddl not in command.upper(), f"the seed job contains {ddl}"

    def test_seed_sql_is_idempotent(self):
        """It runs on every deploy, so every INSERT must tolerate already being there."""
        path = _MODULE / "database" / "SPECS" / "seed.sql"
        text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        for statement in text.split(";"):
            if not re.search(r"\bINSERT\s+INTO\b", statement, re.I):
                continue
            upper = statement.upper()
            assert "ON CONFLICT" in upper or "WHERE NOT EXISTS" in upper, (
                f"non-idempotent INSERT: {' '.join(statement.split())[:70]}"
            )


class TestFrameworkTables:
    """Declared where they are used — not everywhere, and not nowhere."""

    def test_epoch_table_is_declared_because_audit_reads_it(self):
        audit = (_MODULE / "backend" / "SOURCES" / "app" / "audit.py").read_text(encoding="utf-8")
        assert "module_runtime_meta" in audit, "audit.py no longer reads the epoch"
        framework = (_MODULE / "backend" / "SOURCES" / "app" / "framework_models.py").read_text(
            encoding="utf-8"
        )
        assert "__tablename__ = 'module_runtime_meta'" in framework, (
            "audit.py reads module_runtime_meta but no model declares it — every read will fall "
            "back to a per-process instant, silently"
        )

    def test_a_migration_creates_it(self):
        versions = _MODULE / "backend" / "SOURCES" / "alembic" / "versions"
        migrations = "".join(p.read_text(encoding="utf-8") for p in versions.glob("*.py"))
        assert "module_runtime_meta" in migrations

    def test_the_seed_job_writes_the_epoch(self):
        command = " ".join(str(c) for c in (_SERVICES[BOOTSTRAP].get("command") or []))
        assert "system_epoch" in command
        assert "ON CONFLICT" in command.upper(), "the epoch write must be idempotent"

    def test_the_seed_step_is_not_ledger_guarded(self):
        """Guarding an idempotent script buys nothing and hides a re-run that was needed."""
        command = " ".join(str(c) for c in (_SERVICES[BOOTSTRAP].get("command") or []))
        assert "script_key" not in command, (
            "the seed step is ledger-guarded again; seed.sql runs on every deploy"
        )
