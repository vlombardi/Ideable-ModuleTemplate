"""The framework DDL is emitted as named, reversible operations — and the Rewriter emits it.

Phase B of the entity-ddl work. Phase A checks that the DDL is *there*; this checks that a new
entity gets it without anyone typing it.

Stack-free on purpose: it imports the operation module and drives the Rewriter with a synthetic
`CreateTableOp`, so it runs in the CI gate where there is no database and no Alembic environment.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_ALEMBIC = Path(__file__).resolve().parents[1] / "SOURCES" / "alembic"
_OPS = _ALEMBIC / "framework_ops.py"
_ENV = _ALEMBIC / "env.py"

alembic_ops = pytest.importorskip(
    "alembic.operations.ops",
    reason="alembic is a backend runtime dependency; install requirements-dev.txt to run this",
)


def _framework_ops():
    spec = importlib.util.spec_from_file_location("framework_ops", _OPS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["framework_ops"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestTheOperationsExistAndReverse:
    """A downgrade nobody can write is a downgrade nobody writes."""

    def test_every_operation_registers_on_the_op_namespace(self):
        _framework_ops()
        from alembic.operations import Operations
        for name in ("enable_rls", "disable_rls", "create_tenant_policies",
                     "drop_tenant_policies", "create_hypertable"):
            assert hasattr(Operations, name), f"op.{name}() is not registered"

    def test_rls_and_policies_reverse_to_their_opposites(self):
        f = _framework_ops()
        assert isinstance(f.EnableRLSOp("t").reverse(), f.DisableRLSOp)
        assert isinstance(f.DisableRLSOp("t").reverse(), f.EnableRLSOp)
        assert isinstance(f.CreateTenantPoliciesOp("t").reverse(), f.DropTenantPoliciesOp)

    def test_the_hypertable_refuses_to_pretend_it_can_be_reversed(self):
        """TimescaleDB has no un-hypertable. Raising is the honest failure.

        A `reverse()` that returned something plausible would hand back a database the previous
        revision does not describe, and the downgrade would report success.
        """
        f = _framework_ops()
        with pytest.raises(NotImplementedError, match="cannot be reversed"):
            f.CreateHypertableOp("t_version").reverse()

    def test_enable_rls_emits_force_as_well(self):
        """ENABLE alone leaves the table OWNER exempt from every policy, and on a fresh install the
        application role IS the owner — so ENABLE without FORCE is no isolation at all."""
        body = _OPS.read_text(encoding="utf-8")
        impl = body[body.index("def _enable_rls("):body.index("def _disable_rls(")]
        assert "ENABLE ROW LEVEL SECURITY" in impl and "FORCE ROW LEVEL SECURITY" in impl

    def test_the_policies_fail_closed_when_no_tenant_is_set(self):
        """`current_setting(…, TRUE)` returns NULL rather than erroring, so an unscoped session
        matches no rows. Without the TRUE the query would ERROR, which is louder but also breaks
        every legitimate unscoped read such as a migration."""
        body = _OPS.read_text(encoding="utf-8")
        impl = body[body.index("def _create_tenant_policies("):body.index("def _drop_tenant_policies(")]
        assert "current_setting('{guc}', TRUE)" in impl
        assert "tenant_isolation" in impl and "tenant_cross_read" in impl


class TestTheRewriterEmitsTheWholeBlock:
    """One CreateTableOp in, the framework DDL out — written into the migration for review."""

    @staticmethod
    def _expand(table: str, tenant_scoped: dict, versioned: set, filterable: dict | None = None):
        """Drive the rewrite rule directly, with the model facts injected.

        env.py cannot be imported here: it opens a database connection and reads DATABASE_URL. The
        rule itself is pure, so it is exercised with the same inputs env.py would compute.
        """
        f = _framework_ops()
        import sqlalchemy as sa
        op = alembic_ops.CreateTableOp(table, [sa.Column("id", sa.Integer(), primary_key=True)])

        # Run env.py's ACTUAL rule, lifted from the file — not a copy of it. The previous version of
        # this helper re-implemented the lookup, so the helper and env.py could disagree and the
        # tests would still be green. They did disagree, and a version table lost its RLS.
        src = _ENV.read_text(encoding="utf-8")
        body = src[src.index("def _expand_new_table("):src.index("\ndef _include_name(")]
        ns = {"_TENANT_SCOPED": tenant_scoped, "_VERSIONED": versioned, "framework_ops": f,
              "_FILTERABLE": filterable or {}, "alembic_ops": alembic_ops}
        exec(compile(body, str(_ENV), "exec"), ns)
        return ns["_expand_new_table"](None, None, op), f

    def test_a_tenant_scoped_table_gets_rls_and_both_policies(self):
        out, f = self._expand("assets", {"assets": True}, set())
        kinds = [type(o).__name__ for o in out]
        assert kinds == ["CreateTableOp", "EnableRLSOp", "CreateTenantPoliciesOp"]

    def test_the_rewrite_rule_does_not_emit_the_hypertable_inline(self):
        """It is appended at the end of the migration instead — see the ordering test below."""
        out, _ = self._expand("assets_version", {"assets": True}, {"assets"})
        assert "CreateHypertableOp" not in [type(o).__name__ for o in out]

    def test_a_version_table_is_tenant_scoped_even_though_its_own_entry_says_False(self):
        """The map production actually builds, including Continuum's `False` for the twin.

        This is the case the suite could not see before. Continuum GENERATES the version class, and
        the generated class has no `__tenant_scoped__` — so it lands in the map as an explicit
        False. A lookup that reads the table's own entry first finds that False and skips RLS, and
        the audit twin ships partitioned but unprotected: one tenant's history readable by every
        other, in a migration that looks complete.

        The earlier test passed a map with NO version key, which exercised the fallback that
        production never reaches.
        """
        out, _ = self._expand(
            "assets_version",
            {"assets": True, "assets_version": False},   # <- exactly what the registry yields
            {"assets"},
        )
        kinds = [type(o).__name__ for o in out]
        assert "EnableRLSOp" in kinds and "CreateTenantPoliciesOp" in kinds, (
            "the audit twin of a tenant-scoped table got no row-level security — "
            "check_entity_ddl.py (Phase A) rejects exactly this, so the generator would be "
            "emitting a migration the gate forbids"
        )

    def test_a_twin_of_a_global_table_stays_global(self):
        """The mirror case, so the fix is `read the base`, not `always add RLS to *_version`."""
        out, _ = self._expand(
            "registry_version", {"registry": False, "registry_version": False}, {"registry"}
        )
        kinds = [type(o).__name__ for o in out]
        assert "EnableRLSOp" not in kinds, "a deliberately global table's twin acquired policies"

    def test_a_table_that_is_not_tenant_scoped_gets_nothing_extra(self):
        """`__tenant_scoped__ = False` is a real answer, not a missing one — a deliberately global
        table must not acquire policies that would hide its rows from everyone."""
        out, _ = self._expand("framework_registry", {"framework_registry": False}, set())
        assert [type(o).__name__ for o in out] == ["CreateTableOp"]


class TestFilterableColumnsGetTheirTrigramIndexes:
    """The ninth step. Without it a developer follows the generator and STILL fails Phase A's gate.

    These indexes are excluded from the autogenerate diff on purpose (an expression index cannot be
    round-tripped — the diff proposes DROP+CREATE forever). Excluded *and* not emitted, they would
    never be written at all, so the exclusion is exactly why the Rewriter has to emit them.
    """

    def test_each_filterable_column_gets_a_gin_trigram_index(self):
        out, _ = TestTheRewriterEmitsTheWholeBlock._expand(
            "assets", {"assets": True}, set(), {"assets": ("name", "description")}
        )
        idx = [o for o in out if type(o).__name__ == "CreateIndexOp"]
        assert len(idx) == 2, f"expected one index per filterable column, got {len(idx)}"
        for o, col in zip(idx, ("name", "description")):
            assert o.kw.get("postgresql_using") == "gin"
            assert "trgm" in str(o.kw.get("postgresql_ops")), (
                "a plain GIN index does not serve `ILIKE '%term%'` — it needs gin_trgm_ops"
            )

    def test_a_table_with_no_filterable_columns_gets_no_index(self):
        out, _ = TestTheRewriterEmitsTheWholeBlock._expand(
            "assets", {"assets": True}, set(), {"assets": ()}
        )
        assert not [o for o in out if type(o).__name__ == "CreateIndexOp"]

    def test_the_emitted_index_satisfies_phase_a(self):
        """Close the loop: the name and shape must be what check_entity_ddl.py looks for, or the
        generator writes an index the gate does not recognise."""
        out, _ = TestTheRewriterEmitsTheWholeBlock._expand(
            "assets", {"assets": True}, set(), {"assets": ("name",)}
        )
        op = next(o for o in out if type(o).__name__ == "CreateIndexOp")
        rendered = (f"CREATE INDEX {op.index_name} ON {op.table_name} USING gin "
                    f"(name gin_trgm_ops);")
        import re
        pattern = (r"CREATE INDEX[^;]*ON\s+(?:\w+\.)?assets\s+USING\s+gin\s*\("
                   r"[^)]*\bname\b[^)]*gin_trgm_ops")
        assert re.search(pattern, rendered, re.I | re.S), (
            f"Phase A's checker would not match the emitted index: {rendered}"
        )


class TestTheDriftExclusionIsStructuralNotNameBased:
    """A module that names its trigram index anything else must still be excluded from the diff."""

    @staticmethod
    def _include_object():
        src = _ENV.read_text(encoding="utf-8")
        body = src[src.index("def _include_object("):]
        body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
        import sqlalchemy as sa
        ns = {"sa": sa}
        exec(compile(body, str(_ENV), "exec"), ns)
        return ns["_include_object"]

    def test_a_trigram_index_with_an_unconventional_name_is_excluded(self):
        import sqlalchemy as sa
        fn = self._include_object()
        md = sa.MetaData()
        tbl = sa.Table("assets", md, sa.Column("name", sa.String(255)))
        idx = sa.Index("assets_search", tbl.c.name,
                       postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"})
        assert fn(idx, "assets_search", "index", True, None) is False, (
            "excluded only by the `_trgm` name suffix — a module using any other convention gets "
            "the perpetual DROP+CREATE this function exists to prevent"
        )

    def test_an_ordinary_index_is_still_compared(self):
        import sqlalchemy as sa
        fn = self._include_object()
        md = sa.MetaData()
        tbl = sa.Table("assets", md, sa.Column("name", sa.String(255)))
        idx = sa.Index("ix_assets_name", tbl.c.name)
        assert fn(idx, "ix_assets_name", "index", True, None) is True, (
            "a plain index must stay in the diff, or real drift stops being reported"
        )


class TestEnvCanActuallyImportTheOperations:
    """The ops must be importable the way ALEMBIC loads env.py — not the way a test does.

    This class exists because everything else passed while the deployment failed. Alembic loads
    `env.py` and every migration through `load_python_file`, which executes the file **without
    putting its directory on `sys.path`**. So `import framework_ops` — a module sitting right
    beside env.py — raised `ModuleNotFoundError` in the migrations job, while the unit tests loaded
    it by explicit path and saw nothing wrong.

    The lesson is narrow and worth keeping: a test that loads a module differently from production
    is not testing the import.
    """

    def test_env_puts_its_own_directory_on_sys_path_before_importing(self):
        code = [
            ln for ln in _ENV.read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        ]
        insert = next(
            (i for i, ln in enumerate(code)
             if "sys.path.insert" in ln and "dirname(os.path.abspath(__file__))" in ln
             and "dirname(os.path.dirname" not in ln),
            None,
        )
        assert insert is not None, (
            "env.py does not put its OWN directory on sys.path. Alembic's loader does not do it, "
            "so `import framework_ops` fails at migration time — the deploy dies on "
            "ModuleNotFoundError while every unit test still passes."
        )
        imp = next((i for i, ln in enumerate(code) if ln.startswith("import framework_ops")), None)
        assert imp is not None and insert < imp, (
            "the sys.path insert must come BEFORE the framework_ops import"
        )

    def test_the_operations_import_with_only_the_alembic_dir_on_the_path(self):
        """Reproduce Alembic's condition exactly: that directory, and nothing else added."""
        import subprocess
        r = subprocess.run(
            [sys.executable, "-c", "import framework_ops; print(framework_ops.DEFAULT_CHUNK_INTERVAL)"],
            cwd=str(_ALEMBIC), capture_output=True, text=True,
        )
        assert r.returncode == 0, f"framework_ops is not importable from its own directory:\n{r.stderr}"


class TestTheModelFactsAreReadTheWayEnvReadsThem:
    """Build the tenant/versioned maps from the REAL mapper registry, including Continuum's classes.

    The Rewriter tests above inject these maps, which is fine for the rule but blind to how they are
    built — and that is where the second deploy failure was. SQLAlchemy-Continuum GENERATES the
    version classes, and a generated class has `__table__` but no `__tablename__`, so reading the
    attribute raised AttributeError and killed the migrations job. `m.local_table.name` is the
    answer that holds for declared and generated classes alike.
    """

    @staticmethod
    def _registry():
        sys.path.insert(0, str(_ALEMBIC.parent))
        from sqlalchemy.orm import configure_mappers
        from app.database import Base
        from app import models  # noqa: F401
        from app import framework_models  # noqa: F401
        configure_mappers()          # Continuum builds its version classes here
        return Base

    def test_every_mapped_class_yields_a_table_name(self):
        Base = self._registry()
        for m in Base.registry.mappers:
            if m.local_table is None:
                continue
            assert m.local_table.name, f"{m.class_.__name__} has no resolvable table name"

    def test_a_continuum_version_class_is_present_and_has_no_tablename(self):
        """Pin the exact shape that broke it, so a future refactor cannot quietly reintroduce the
        `__tablename__` assumption."""
        Base = self._registry()
        version_classes = [
            m.class_ for m in Base.registry.mappers
            if m.local_table is not None and m.local_table.name.endswith("_version")
        ]
        assert version_classes, "Continuum generated no version classes — the premise has changed"
        assert not hasattr(version_classes[0], "__tablename__"), (
            "a Continuum version class now HAS __tablename__; the comment in env.py explaining why "
            "local_table.name is used should be revisited"
        )

    def test_the_maps_env_builds_include_the_version_tables(self):
        Base = self._registry()
        tenant_scoped = {
            m.local_table.name: bool(getattr(m.class_, "__tenant_scoped__", False))
            for m in Base.registry.mappers if m.local_table is not None
        }
        assert any(t.endswith("_version") for t in tenant_scoped), (
            "no version table in the map — the Rewriter would never partition an audit twin"
        )


class TestDriftIsControlledDeliberately:
    """Two classes of object must stay OUT of the diff, for different reasons."""

    def test_timescale_internals_are_filtered_before_reflection(self):
        """`include_name` runs earlier than `include_object`, so chunk tables are never reflected."""
        env = _ENV.read_text(encoding="utf-8")
        assert "include_name=_include_name" in env
        assert "_timescaledb_internal" in env

    def test_expression_indexes_are_excluded_from_the_diff(self):
        """Autogenerate cannot round-trip an expression index: it proposes drop+create on every run
        against a database that already matches. They are asserted by check_entity_ddl.py instead,
        which reads the schema rather than diffing it."""
        env = _ENV.read_text(encoding="utf-8")
        assert "include_object=_include_object" in env
        assert '_trgm' in env

    def test_the_rewriter_is_actually_installed_in_both_modes(self):
        """Offline (`--sql`) and online autogenerate are configured separately; wiring one and not
        the other is how a generator silently stops running for half the callers."""
        env = _ENV.read_text(encoding="utf-8")
        assert env.count("process_revision_directives=_process_revision_directives") == 2

    def test_the_hypertable_conversion_is_appended_after_the_indexes(self):
        """`create_hypertable` LAST, or the migration dies on a duplicate index.

        TimescaleDB's conversion creates its own default index on the time column, named
        `<table>_<time_column>_idx` — the same name autogenerate emits for the `issued_at DESC`
        index the model declares. Convert before that index exists and the upgrade fails with
        `relation "…_version_issued_at_idx" already exists`; convert after and TimescaleDB adopts
        the existing index instead.

        Found by applying a generated migration to a real database. No amount of reading the
        generated file would have shown it.
        """
        import sqlalchemy as sa
        f = _framework_ops()
        src = _ENV.read_text(encoding="utf-8")
        body = src[src.index("def _convert_hypertables_last("):src.index("def _process_revision_directives(")]
        ns = {"_VERSIONED": {"assets"}, "framework_ops": f, "alembic_ops": alembic_ops}
        exec(compile(body, str(_ENV), "exec"), ns)

        class _Ops:
            def __init__(self, ops): self.ops = ops
        col = [sa.Column("id", sa.Integer(), primary_key=True)]
        upgrade = _Ops([
            alembic_ops.CreateTableOp("assets_version", col),
            alembic_ops.CreateIndexOp("assets_version_issued_at_idx", "assets_version", ["issued_at"]),
        ])
        ns["_convert_hypertables_last"](upgrade)
        kinds = [type(o).__name__ for o in upgrade.ops]
        assert kinds[-1] == "CreateHypertableOp", (
            f"the conversion must be last, got {kinds} — converting before the index is created "
            f"fails the upgrade on a duplicate relation name"
        )

    def test_a_table_that_is_not_versioned_is_never_converted(self):
        f = _framework_ops()
        import sqlalchemy as sa
        src = _ENV.read_text(encoding="utf-8")
        body = src[src.index("def _convert_hypertables_last("):src.index("def _process_revision_directives(")]
        ns = {"_VERSIONED": set(), "framework_ops": f, "alembic_ops": alembic_ops}
        exec(compile(body, str(_ENV), "exec"), ns)

        class _Ops:
            def __init__(self, ops): self.ops = ops
        upgrade = _Ops([alembic_ops.CreateTableOp(
            "assets_version", [sa.Column("id", sa.Integer(), primary_key=True)])])
        ns["_convert_hypertables_last"](upgrade)
        assert len(upgrade.ops) == 1, "converted a table nothing declared as versioned"
