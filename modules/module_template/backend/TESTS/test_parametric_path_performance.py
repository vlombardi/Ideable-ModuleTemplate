"""The parametric path costs what the hand-written one cost.

The premise of the whole entity-registry plan is that genericity is free when it lives at import
time and in SQL construction, and that the ways generic layers get slow are avoidable and nameable.
That is a claim, and this file is where it stops being one.

WHAT IS COMPARED. `TESTS/benchmark/bespoke_baseline.py` — the hand-written `items` query frozen at
the last commit before it was generalised — against `app.entities.list_entity`, over the same rows,
in the same session, with the same filter and sort. Today's `crud.list_items` would compare a
function to itself: it already calls the shared core.

WHAT IS ASSERTED, AND WHY IT IS A RATIO. Absolute timings on a developer laptop, in a container,
against a shared database say nothing portable. What is portable is the RELATIONSHIP between two
paths measured in the same process microseconds apart, so the assertion is that the parametric path
is within a stated multiple of the baseline — and the numbers are printed either way, because the
margin passing is less informative than what it passed by.

SHALLOW AND DEEP, because they fail differently: a shallow page exposes per-request overhead (schema
resolution, column maps — anything that slipped out of import time), and a deep page exposes whether
keyset pagination survived generalisation.
"""
import statistics
import time

import pytest

import framework_sources

# Asserts on elapsed time: re-run once straight after a failure and reported by name if it passes only on
# the retry (rules/testing-guidelines.md § A timing-sensitive test is retried once, and says so).
pytestmark = pytest.mark.timing_sensitive

#: How much slower the parametric path may be before this is a real regression.
#:
#: Generous on purpose. The two paths compile to the same SQL, so the honest expectation is parity
#: and anything approaching this multiple means per-request work crept in. A tight bound would fail
#: on scheduler noise and be disabled within a month, which is worse than a loose bound that holds.
MARGIN = 2.0

#: Below this, the measurement is noise: two queries differing by tens of microseconds tell you
#: about the machine, not the code. The ratio is reported and not asserted under it.
#:
#: 0.5 ms, chosen AGAINST a measurement rather than by feel. The first value here was 2 ms, which
#: sat above the observed baseline of ~1.6 ms — so both timing assertions skipped and the file
#: reported "3 passed, 2 skipped" while asserting nothing about performance at all. A floor must be
#: below what the thing actually costs, or it is an off switch.
NOISE_FLOOR_SECONDS = 0.0005

REPEATS = 12
ROWS = 60


@pytest.fixture(scope="module")
def bespoke(app_module):
    from benchmark import bespoke_baseline
    return bespoke_baseline


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _time(call, repeats: int = REPEATS) -> tuple[float, float]:
    """(p50, p95) seconds over `repeats` calls, discarding the first.

    The first call is dropped rather than averaged in: it pays for the statement cache being cold
    and for whatever the connection does once, and including it would measure the warm-up of
    whichever path happened to run first.
    """
    call()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        call()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples), _percentile(samples, 0.95)


@pytest.fixture
def seeded(app_module, db_session, tenant_scope_factory):
    """`ROWS` rows in one tenant, and the marker that selects exactly them."""
    scope = tenant_scope_factory()
    marker = f"perf-{next(iter(scope.tenant_ids))}"
    items = app_module.entities.get_entity_descriptor('items')
    created = []
    for index in range(ROWS):
        payload = items.create_schema(name=marker, description=f"row-{index:04d}")
        created.append(app_module.entities.create_entity_row(db_session, items, payload, scope).id)
    try:
        yield scope, marker, created
    finally:
        for row_id in created:
            fresh = app_module.entities.get_entity_row(db_session, items, row_id, scope,
                                                       for_write=True)
            if fresh is not None:
                app_module.entities.delete_entity_row(db_session, items, fresh)


def _report(label: str, base: tuple[float, float], para: tuple[float, float]) -> float:
    ratio = para[1] / base[1] if base[1] else 1.0
    print(
        f"\n[perf] {label}: baseline p50={base[0] * 1e3:.2f}ms p95={base[1] * 1e3:.2f}ms | "
        f"parametric p50={para[0] * 1e3:.2f}ms p95={para[1] * 1e3:.2f}ms | ratio p95={ratio:.2f}×"
    )
    return ratio


class TestTheParametricPathIsNotSlower:
    def test_a_shallow_page_with_a_filter_and_a_sort(self, app_module, db_session, seeded):
        """Per-request overhead: anything that slipped out of import time shows here."""
        scope, marker, _ = seeded
        items = app_module.entities.get_entity_descriptor('items')

        base = _time(lambda: bespoke_call(db_session, scope, marker))
        para = _time(lambda: app_module.entities.list_entity(
            db_session, items, scope, filters={'name': marker},
            sort_by='name', sort_order='asc', limit=20,
        ))
        ratio = _report("shallow", base, para)
        if base[1] < NOISE_FLOOR_SECONDS:
            pytest.skip(f"baseline p95 {base[1] * 1e3:.2f}ms is below the noise floor")
        assert ratio <= MARGIN, (
            f"the parametric path is {ratio:.2f}× the baseline at p95, above the {MARGIN}× margin. "
            f"The two compile to the same SQL, so this is per-request work that belongs at import "
            f"time — see the plan's design note 'where the genericity is allowed to live'."
        )

    def test_a_deep_page_by_cursor(self, app_module, db_session, seeded):
        """Whether keyset pagination survived generalisation: a cursor seeks, an offset scans."""
        scope, marker, created = seeded
        items = app_module.entities.get_entity_descriptor('items')
        midpoint = sorted(created)[len(created) // 2]

        base = _time(lambda: bespoke_call(db_session, scope, marker, after_id=midpoint))
        para = _time(lambda: app_module.entities.list_entity(
            db_session, items, scope, filters={'name': marker},
            sort_by='id', sort_order='asc', limit=20, after_id=midpoint,
        ))
        ratio = _report("deep (cursor)", base, para)
        if base[1] < NOISE_FLOOR_SECONDS:
            pytest.skip(f"baseline p95 {base[1] * 1e3:.2f}ms is below the noise floor")
        assert ratio <= MARGIN, (
            f"the parametric path is {ratio:.2f}× the baseline at p95 on a cursor page. A cursor "
            f"that degraded to an offset scan is the regression this catches."
        )


def bespoke_call(db_session, scope, marker, after_id=None):
    from benchmark import bespoke_baseline
    if after_id is None:
        return bespoke_baseline.bespoke_list_items(
            db_session, scope, name=marker, sort_by='name', sort_order='asc', limit=20)
    return bespoke_baseline.bespoke_list_items(
        db_session, scope, name=marker, sort_by='id', sort_order='asc', limit=20,
        after_id=after_id)


class TestTheRulesThatKeepItThatWay:
    """The three mechanical properties the design note names. Each was a way a generic layer gets
    slow, and each is checkable without timing anything."""

    def test_the_page_query_is_not_compiled_with_literal_binds(self):
        """Bound parameters, or the compiled-statement cache never hits.

        `_estimated_total` compiles with `literal_binds=True` deliberately — EXPLAIN cannot take
        parameters — and the two sit in the same file, which is exactly how the exception spreads
        to the rule. So the assertion is scoped: the list query itself must not do it.

        Read from the framework package rather than from `app.crud`, which re-exports it: the query
        core is `ideable_api.query` and is shared by every module's backend.
        """
        text = framework_sources.read(framework_sources.QUERY)
        start = text.index("def list_entities(")
        list_body = text[start:text.index("\ndef ", start + 10)]
        assert "literal_binds" not in list_body, (
            "the list query compiles with literal_binds, so every distinct filter value produces a "
            "distinct SQL string and the compiled-statement cache can never hit"
        )

    def test_every_entity_declares_an_eager_load_plan_for_its_relationships(self, app_module):
        """The N+1 guard: a relationship a read schema exposes must be in the eager-load plan.

        Vacuous while no declared entity has a relationship, and deliberately written now rather
        than with the first one: the entity that introduces a relationship should meet this check
        already in place, not have it written to fit what it happens to do.
        """
        from sqlalchemy import inspect as sa_inspect

        for key, descriptor in app_module.entities.all_entity_descriptors().items():
            relationships = {rel.key for rel in sa_inspect(descriptor.model).relationships}
            if not relationships:
                continue
            exposed = relationships & set(descriptor.read_schema.model_fields)
            if not exposed:
                continue
            planned = " ".join(str(option) for option in descriptor.eager_load)
            missing = sorted(name for name in exposed if name not in planned)
            assert not missing, (
                f"entity {key!r} exposes {missing} in its read schema with no eager-load plan "
                f"covering them: every row of a page will fetch them one query at a time"
            )

    def test_the_registry_is_frozen_so_per_entity_work_happens_once(self, app_module):
        """Rule 1 of the design note, checked rather than asserted in prose."""
        assert app_module.entities.is_registry_frozen() is True
