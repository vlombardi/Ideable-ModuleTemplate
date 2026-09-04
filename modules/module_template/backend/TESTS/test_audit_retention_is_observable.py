"""Audit retention reports what it is doing, instead of running unobserved.

Retention is a TimescaleDB policy added by `scripts/runtime/config/audit-retention.sh`, and it is
**off unless `AUDIT_RETAIN_FOR` is set**. That gives two silent states, not one: never enabled, and
enabled but no longer dropping anything. From outside they look identical — the audit tables simply
grow — and the first symptom is a disk alert that points nowhere near retention.

Deferred by Task 12 *"to the Task 7 observability work"*, which had already closed, so the item was
orphaned: nothing listed it and nothing was going to pick it up. It matters more now that host_app's
nine version tables are hypertables too, giving retention ten tables to act on rather than one.

**Why there is no `rows_pruned` counter.** The pruning is done by a background policy inside the
database, not by this process, so the application never observes the event — a counter it increments
could only ever read zero. The oldest row's age is the same information taken from state rather than
from an event: near the retention window when retention works, growing without bound when it stops.
A gauge that can be wrong is worth more than a counter that cannot be right.
"""
import re
from pathlib import Path

_METRICS = Path(__file__).resolve().parents[1] / "SOURCES" / "app" / "metrics.py"

EXPECTED = {
    "audit_table_bytes": "on-disk size, so growth is visible before the disk alert",
    "audit_table_chunks": "chunk count; unbounded growth means retention is not dropping",
    "audit_oldest_data_age_seconds": "the one that distinguishes 'retention works' from 'retention stopped'",
}


def _src() -> str:
    return _METRICS.read_text(encoding="utf-8")


def test_the_three_gauges_are_declared():
    src = _src()
    missing = sorted(n for n in EXPECTED if f"'{n}'" not in src and f'"{n}"' not in src)
    assert not missing, (
        "audit retention metrics missing: "
        + ", ".join(f"{n} ({EXPECTED[n]})" for n in missing)
    )


def test_they_are_labelled_per_table():
    """Ten audit tables share one metric name; without a label they would overwrite each other."""
    src = _src()
    block = src[src.index("AUDIT_TABLE_BYTES"):src.index("def _observe_runtime_state")]
    for name in EXPECTED:
        assert "['table']" in block, f"{name} is not labelled by table"


def test_the_observer_is_reachable_from_the_scrape():
    """A declared gauge nobody refreshes reports 0 for ever, which reads as a healthy empty table."""
    src = _src()
    assert "_observe_audit_state()" in src, "the audit observer is never called"
    runtime = src[src.index("def _observe_runtime_state"):src.index("def _observe_audit_state")]
    assert "_observe_audit_state()" in runtime, (
        "the audit observer is defined but not invoked from the scrape path, so every audit gauge "
        "would report 0 for ever — indistinguishable from an empty audit trail"
    )


def test_the_tables_are_discovered_not_listed():
    """A hardcoded table list stops covering a newly added entity, silently.

    This is the blind spot the metric exists to remove, so reintroducing it in the metric's own
    query would be self-defeating.
    """
    src = _src()
    body = src[src.index("def _observe_audit_state"):src.index("def instrument")]
    assert "pg_class" in body or "information_schema" in body, (
        "the audit tables are not discovered from the catalog"
    )
    assert "_version" in body, "the discovery does not match the Continuum version tables"
    # Derived from THIS module's own models, so the check means something in every project. A fixed
    # list of the reference module's table names would pass trivially in a module that has none of
    # them — asserting the absence of a name that could not appear anyway.
    models = _METRICS.parent / "models.py"
    entities = re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]", models.read_text(encoding="utf-8"))
    assert entities, "app/models.py declares no __tablename__ — the extraction has drifted"
    for entity in entities:
        for literal in (f'"{entity}_version"', f"'{entity}_version'", f'"{entity}"', f"'{entity}'"):
            assert literal not in body, (
                f"{literal} is hardcoded in the metrics query — a module with different entities "
                f"would report nothing, which is the silence this metric exists to break"
            )


def test_the_query_is_a_raw_string():
    """The LIKE pattern escapes an underscore; in a normal string that is an invalid escape.

    Python emits SyntaxWarning and the pattern silently means something else. Caught during
    implementation, pinned here.
    """
    src = _src()
    body = src[src.index("def _observe_audit_state"):src.index("def instrument")]
    assert 'text(r"""' in body, (
        "the catalog query is not a raw string, so `\\_` in the LIKE pattern is an invalid escape "
        "sequence — Python warns and the pattern does not mean what it reads as"
    )


def test_a_scrape_failure_is_logged_not_swallowed():
    """A metrics scrape must never fail a request — but it must not vanish either."""
    src = _src()
    tail = src[src.index("_observe_audit_state()"):]
    handler = tail[:tail.index("def _observe_audit_state")] if "def _observe_audit_state" in tail else tail[:400]
    assert "logger.debug" in handler, "an audit-metrics failure is swallowed with no trace"
    assert "jwks" not in handler.lower(), (
        "the audit handler logs a JWKS message — a wrong message in an error handler sends the next "
        "reader to the wrong subsystem"
    )


def test_the_retention_job_still_gates_on_the_variable():
    """The metric's premise: retention is OFF unless AUDIT_RETAIN_FOR is set, so 'no pruning' is a
    legitimate state and the gauge must be read against that variable, not alone."""
    job = Path(__file__).resolve().parents[4] / "scripts" / "runtime" / "config" / "audit-retention.sh"
    if not job.is_file():
        return  # maintainer-only path in some checkouts; the gauges above are what this file guards
    assert "AUDIT_RETAIN_FOR" in job.read_text(encoding="utf-8"), (
        "the retention job no longer gates on AUDIT_RETAIN_FOR; the oldest-data gauge is interpreted "
        "against that window, so this test's premise would be stale"
    )
