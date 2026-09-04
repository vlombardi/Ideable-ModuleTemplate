"""
Migration tests for module_template.

These guard the rules in database/SPECS/ideable-framework-specs/schema-workflow.md — the model is
the schema, only Alembic writes it — and each one exists because the corresponding mistake was
actually made during this module's adoption of Alembic:

- A baseline inferred a whole schema from one probe, so a fresh install silently came up without
  the Continuum audit tables.
- `create_all()` created what was missing and altered nothing, so no deployed schema could evolve.
- A second owner of the schema (`datamodel.sql`) left four `au_*` columns in deployed databases
  that no file in the repository declared.

The revision-graph and unconditionality checks are source-level on purpose: they must fail in CI
when someone writes a bad migration, which is before any database exists to run it against.
"""
import re
from pathlib import Path

import pytest
import requests

# Derived, never named: this file is force-synced verbatim into every remote module project, where
# the module and its entities carry the module's own names (rules/testing-guidelines.md).
_MODULE_DIR = Path(__file__).resolve().parents[2]


def _entity_tables() -> set[str]:
    """The tables this module AUTHORS, read from the one authored definition.

    A literal `template_items` in a force-synced test asserts about the reference module's example
    entity, which a real module does not have — so the check silently stopped applying to the only
    tables it protects. `app/models.py` is the schema's source of truth, and `__tablename__` is
    still the right answer in a module whose entities are companies and assets.
    """
    models = _MODULE_DIR / "backend" / "SOURCES" / "app" / "models.py"
    tables = set(re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]",
                            models.read_text(encoding="utf-8")))
    assert tables, "app/models.py declares no __tablename__ — the extraction has drifted"
    return tables


_BACKEND = Path(__file__).resolve().parents[1]
_SOURCES = _BACKEND / "SOURCES"
_VERSIONS = _SOURCES / "alembic" / "versions"
_APP = _SOURCES / "app"
_COMPOSE = _BACKEND.parents[0] / "docker-compose.yml"

_REVISION_RE = re.compile(r"^revision: str = ['\"]([^'\"]+)['\"]", re.M)
_DOWN_RE = re.compile(r"^down_revision: Union\[str, None\] = (?:['\"]([^'\"]+)['\"]|None)", re.M)
_FILENAME_RE = re.compile(r"^\d{8}_\d{4}_[a-z0-9_]+\.py$")


def _migrations():
    """[(path, revision, down_revision)] for every migration shipped by this module."""
    out = []
    for path in sorted(_VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = _REVISION_RE.search(text)
        assert revision, f"{path.name} declares no revision id"
        down = _DOWN_RE.search(text)
        out.append((path, revision.group(1), down.group(1) if down and down.group(1) else None))
    return out


class TestRevisionGraph:
    """A migration history has to be a single chain, or `upgrade head` is ambiguous."""

    def test_migrations_exist(self):
        assert _migrations(), "no migrations found — the schema has no owner"

    def test_exactly_one_baseline(self):
        roots = [p.name for p, _, down in _migrations() if down is None]
        assert len(roots) == 1, f"expected exactly one baseline (down_revision = None), got {roots}"

    def test_every_down_revision_resolves(self):
        migrations = _migrations()
        known = {rev for _, rev, _ in migrations}
        for path, _, down in migrations:
            if down is not None:
                assert down in known, f"{path.name} points at unknown revision {down!r}"

    def test_single_head(self):
        """Two heads means two people branched the schema and nothing noticed."""
        migrations = _migrations()
        referenced = {down for _, _, down in migrations if down}
        heads = [rev for _, rev, _ in migrations if rev not in referenced]
        assert len(heads) == 1, f"expected one head, found {heads} — the history has forked"

    def test_revision_ids_are_unique(self):
        revisions = [rev for _, rev, _ in _migrations()]
        assert len(revisions) == len(set(revisions)), f"duplicate revision ids: {revisions}"

    def test_filenames_are_chronological(self):
        for path, _, _ in _migrations():
            assert _FILENAME_RE.match(path.name), (
                f"{path.name} does not match YYYYMMDD_HHMM_slug.py — set `file_template` in "
                f"alembic.ini so versions/ reads as a timeline"
            )


class TestOnlyTheBaselineIsConditional:
    """The baseline adopts existing databases, so it branches. Nothing after it may."""

    def test_baseline_is_conditional(self):
        baseline = next(p for p, _, down in _migrations() if down is None)
        text = baseline.read_text(encoding="utf-8")
        assert "sa.inspect" in text, (
            "the baseline must inspect the database: it has to work on both an empty database "
            "and on deployments that predate Alembic"
        )

    def test_baseline_checks_each_table_individually(self):
        """The bug this test exists for: one probe standing in for a whole schema."""
        baseline = next(p for p, _, down in _migrations() if down is None)
        text = baseline.read_text(encoding="utf-8")
        for table in ({"transaction", "transaction_meta"}
                      | {f"{t}_version" for t in _entity_tables()}):
            assert f"'{table}'" in text or f'"{table}"' in text, (
                f"the baseline never mentions {table} — a fresh install would come up without "
                f"an audit trail"
            )

    def test_later_migrations_are_unconditional(self):
        for path, _, down in _migrations():
            if down is None:
                continue
            text = path.read_text(encoding="utf-8")
            assert "sa.inspect" not in text, (
                f"{path.name} inspects the database. Only a baseline may be conditional — a "
                f"migration that branches stops describing the schema."
            )


class TestSchemaHasOneOwner:

    def test_no_create_all_in_sources(self):
        offenders = [
            p.name for p in _APP.glob("*.py")
            if "metadata.create_all(" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"create_all() found in {offenders} — the schema is Alembic's"

    def test_bootstrap_job_contains_no_ddl(self):
        """The bootstrap seeds rows. A bootstrap that created tables produced the au_* drift."""
        compose = _COMPOSE.read_text(encoding="utf-8")
        block = compose.split("SYNC-MANAGED-BEGIN: bootstrap-service")[1]
        block = block.split("SYNC-MANAGED-END: bootstrap-service")[0]
        for ddl in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE"):
            assert ddl not in block.upper(), f"the bootstrap job contains {ddl}"

    def test_generated_schema_is_marked_generated(self):
        """The rendering must announce itself, or someone will edit it and expect it to apply."""
        path = _BACKEND.parents[0] / "database" / "SPECS" / "schema.sql"
        assert path.is_file(), (
            "database/SPECS/schema.sql missing — regenerate with schema.sh schema-sql"
        )
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert "GENERATED" in first, (
            "schema.sql must be the generated rendering of the migrations, not a second "
            "definition of the schema (regenerate: scripts/dev/schema.sh schema-sql)"
        )

    @staticmethod
    def _env_filter(func_name: str, end_marker: str):
        """Lift one filter function out of env.py and return it, callable.

        env.py cannot be imported here — it opens a database connection — but these functions are
        pure, so executing their source is the real thing rather than a description of it.
        """
        import sqlalchemy as sa
        src = (_SOURCES / "alembic" / "env.py").read_text(encoding="utf-8")
        body = src[src.index(f"def {func_name}("):src.index(end_marker)]
        ns = {"sa": sa}
        exec(compile(body, "env.py", "exec"), ns)
        return ns[func_name]

    def test_env_py_hides_no_table_from_autogenerate(self):
        """A table hidden from autogenerate is a table a second owner can write to.

        This asserts the REQUIREMENT — no table is ever excluded — rather than one spelling of it.
        It used to assert that the string `include_object=` never appeared, which banned the
        parameter outright. That over-reached: `include_object` is also how expression indexes are
        kept out of the diff, and an index is not a table, so a correct change (excluding trigram
        GIN indexes, which autogenerate cannot round-trip and therefore proposes DROP+CREATE for on
        every run) read as a violation of an invariant it did not actually breach.

        Same correction, and for the same reason, as `test_job_runs_upgrade_head` below: follow the
        requirement, not the spelling. The requirement is now checked by CALLING the filters, so a
        future edit that really does hide a table fails here — which the string match could not do,
        since any renamed helper would have slipped past it.
        """
        include_object = self._env_filter("_include_object", "\ndef run_migrations_offline(")
        for name in ({"transaction", "alembic_version"} | _entity_tables()
                     | {f"{t}_version" for t in _entity_tables()}):
            assert include_object(None, name, "table", True, None) is True, (
                f"table {name!r} is excluded from autogenerate — every table must be visible or a "
                f"second owner can write to the hidden one"
            )

    def test_env_py_hides_only_timescale_internal_schemas(self):
        """`include_name` may skip TimescaleDB's own schemas — never a schema holding module data.

        Chunks are TimescaleDB's to manage; without this the diff proposes dropping every one of
        them. `public` must always survive the filter.
        """
        include_name = self._env_filter("_include_name", "\ndef _include_object(")
        assert include_name("public", "schema", {}) is True, "the public schema is filtered out"
        assert include_name(None, "schema", {}) is True, "the default schema is filtered out"
        for name in _entity_tables() | {f"{t}_version" for t in _entity_tables()}:
            assert include_name(name, "table", {}) is True, f"table {name!r} is filtered out"
        assert include_name("_timescaledb_internal", "schema", {}) is False, (
            "TimescaleDB's chunk schema is no longer filtered — autogenerate will propose dropping "
            "every chunk of every hypertable"
        )

    def test_configure_mappers_is_called(self):
        env = (_SOURCES / "alembic" / "env.py").read_text(encoding="utf-8")
        assert "configure_mappers()" in env, (
            "without configure_mappers() Continuum's version classes are invisible and "
            "autogenerate proposes dropping the audit trail"
        )


class TestMigrationsJob:
    """Schema changes run once, before any backend serves traffic."""

    def test_job_runs_upgrade_head(self):
        """Assert the property — alembic upgrades to head in exec form — not one spelling of it.

        This used to assert the literal `["alembic", "upgrade", "head"]`. That spelling stopped
        being possible on distroless: the console scripts pip generates live in `/deps/bin`, which
        is not on PATH and could not be put there without a shell to extend it. The job now runs
        `["python", "-m", "alembic", ...]`, which reaches the same entry point through the module
        rather than through a PATH lookup. Asserting the literal made a correct change look like a
        regression, so the assertion follows the requirement instead: some exec-form command in the
        migrations job runs alembic to head.
        """
        compose = _COMPOSE.read_text(encoding="utf-8")
        block = compose.split("SYNC-MANAGED-BEGIN: migrations-job")[1]
        block = block.split("SYNC-MANAGED-END: migrations-job")[0]
        commands = re.findall(r"command:\s*(\[[^\]]*\])", block)
        assert commands, "the migrations job declares no command"
        for raw in commands:
            argv = [a.strip().strip('"\'') for a in raw.strip("[]").split(",")]
            if argv[-3:] == ["alembic", "upgrade", "head"]:
                return
        raise AssertionError(
            f"no exec-form command in the migrations job runs `alembic upgrade head`: {commands}"
        )

    def test_job_never_restarts(self):
        """A restarting one-shot can never satisfy service_completed_successfully."""
        compose = _COMPOSE.read_text(encoding="utf-8")
        block = compose.split("SYNC-MANAGED-BEGIN: migrations-job")[1]
        block = block.split("SYNC-MANAGED-END: migrations-job")[0]
        assert 'restart: "no"' in block

    def test_backend_waits_for_the_schema(self):
        compose = _COMPOSE.read_text(encoding="utf-8")
        assert "service_completed_successfully" in compose


class TestStartupGate:
    """A container must not serve traffic against a schema its code does not expect."""

    @pytest.fixture(scope="class")
    def probe_base_url(self, api_base_url):
        return api_base_url.rsplit("/api", 1)[0]

    def test_startup_reports_the_deployed_revision(self, probe_base_url):
        # A stack-requiring assertion in a force-synced test needs a guard, or it reports a
        # ConnectionError as the module's failure on every project that is not currently running.
        # Found by verify_remote_shape.sh: this passed here only because the maintainer's own stack
        # was listening on the default port. The skip names what is absent, as
        # rules/testing-guidelines.md requires — a bare skip would be indistinguishable from a pass.
        try:
            response = requests.get(f"{probe_base_url}/startup", timeout=10)
        except requests.exceptions.RequestException as exc:
            pytest.skip(
                f"no backend answering at {probe_base_url} "
                f"({type(exc).__name__}) — deploy the module and re-run to exercise the startup gate"
            )
        assert response.status_code == 200, (
            f"/startup returned {response.status_code}: {response.text}. A schema-mismatch here "
            f"means the migrations job has not run against this database."
        )
        body = response.json()
        reported = str(body.get("schema") or body.get("revision") or "")
        heads = [rev for _, rev, _ in _migrations()]
        referenced = {down for _, _, down in _migrations() if down}
        head = next(rev for rev in heads if rev not in referenced)
        assert head in reported or reported == "no migrations shipped", (
            f"/startup reports {reported!r} but this image ships head {head!r} — the deployed "
            f"database is not at the revision this code expects"
        )

    def test_startup_gate_reads_alembic_version(self):
        main = (_APP / "main.py").read_text(encoding="utf-8")
        assert "schema_revision_matches_head()" in main, (
            "/startup must be gated on the schema revision, not only on handlers completing"
        )
        database = (_APP / "database.py").read_text(encoding="utf-8")
        assert "alembic_version" in database
