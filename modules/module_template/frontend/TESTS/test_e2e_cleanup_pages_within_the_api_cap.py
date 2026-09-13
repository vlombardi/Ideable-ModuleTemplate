"""An E2E suite must be able to clean up after itself, and must say so when it cannot.

This file exists because of a silent, permanent leak. `items-crud.spec.ts` finished each run by
listing the items it had created and deleting them:

    const res = await api.get(API_ITEMS, { params: { limit: '500' } })
    if (res.ok()) { ...delete the rows whose name starts with this run's marker... }

The list endpoint caps `limit` at `crud.MAX_PAGE_SIZE` (200 by default), so the request was answered
`422` and `res.ok()` was false. The cleanup therefore deleted NOTHING, on every run, from the day it
was written -- verified in the deployed stack's own log
(`"GET /api/items?limit=500 HTTP/1.1" 422`) and in the audit trail, which held only INSERT and
UPDATE rows for the survivors and never a DELETE.

Two things made it invisible for as long as it lasted, and this file checks both:

1. **The limit was a guess, not a value read from the API.** A number written into a test and capped
   somewhere else is a number free to drift past the cap.
2. **A cleanup that deletes nothing looks exactly like a cleanup with nothing to do.** The suite
   passed. The residue was found only by looking at the database: two rows per run, each carrying
   the run's own `TEST_TENANT` id, which `--purge` had since deleted -- so the rows accumulated
   pointing at tenants that no longer existed.

Both checks are STATIC: they read the module's own backend cap and the module's own specs, so there
is no stack to stand up and nothing to skip. The cap is DISCOVERED from the backend rather than
restated, which is the whole point -- restating it here would recreate the drift.

Remote-safe: the module directory, the backend and the specs are all discovered by glob. Nothing is
named after a slug, because `module-init.sh` renames the module and its entity specs.
"""
import re
from pathlib import Path

import pytest

MODULE_FRONTEND = Path(__file__).resolve().parents[1]   # modules/<THIS MODULE>/frontend
MODULE_ROOT = MODULE_FRONTEND.parent
REPO = MODULE_ROOT.parents[1]

SPEC_DIR = MODULE_FRONTEND / "TESTS" / "playwright" / "tests"
CRUD_SOURCE = MODULE_ROOT / "backend" / "SOURCES" / "app" / "crud.py"

#: The default the backend falls back to when MAX_PAGE_SIZE is unset in the environment.
_CAP_PATTERN = re.compile(r"MAX_PAGE_SIZE\s*=\s*int\(\s*os\.getenv\(\s*['\"]MAX_PAGE_SIZE['\"]\s*,\s*['\"](\d+)['\"]")

#: A page size written straight into a request: `limit: '500'`, `limit: 500`, `limit=500`.
_LITERAL_LIMIT = re.compile(r"limit(?:\s*[:=]\s*|=)['\"]?(\d+)")

#: A page size passed through a constant: `limit: String(CLEANUP_PAGE_SIZE)`.
_NAMED_LIMIT = re.compile(r"limit\s*:\s*String\(\s*(\w+)\s*\)")


#: Line and block comments. Stripped before scanning, because a comment EXPLAINING the rejected
#: page size is not a request for it — the first version of this check failed on its own
#: description of the bug. Naive about `//` inside string literals, which is acceptable here: the
#: cost is a false positive on a URL written in a comment, never a missed real request.
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def _specs() -> list[Path]:
    return sorted(p for p in SPEC_DIR.glob("*.spec.ts") if "node_modules" not in p.parts)


def _code(spec: Path) -> str:
    """The spec with its comments removed."""
    return _COMMENTS.sub("", spec.read_text(encoding="utf-8"))


def api_page_cap() -> int:
    """The largest `limit` this module's API accepts, read from the backend itself."""
    match = _CAP_PATTERN.search(CRUD_SOURCE.read_text(encoding="utf-8"))
    assert match, (
        f"MAX_PAGE_SIZE could not be read from {CRUD_SOURCE.relative_to(REPO)} — the cap this file "
        f"checks against must come from the backend, never from a number repeated here"
    )
    return int(match.group(1))


def _declared_numbers(src: str) -> dict[str, int]:
    return {name: int(value) for name, value in re.findall(r"const\s+(\w+)\s*=\s*(\d+)\b", src)}


def _requested_limits(src: str) -> list[int]:
    """Every page size the spec asks the API for, whether written inline or via a constant."""
    numbers = _declared_numbers(src)
    limits = [int(n) for n in _LITERAL_LIMIT.findall(src)]
    limits += [numbers[name] for name in _NAMED_LIMIT.findall(src) if name in numbers]
    return limits


def _after_all_blocks(src: str) -> list[str]:
    """The body of each `test.afterAll(...)`, taken to the next test or the end of the describe."""
    blocks: list[str] = []
    for match in re.finditer(r"test\.afterAll\(", src):
        rest = src[match.end():]
        stop = re.search(r"\n  (?:test|test\.\w+)\(", rest)
        blocks.append(rest[: stop.start()] if stop else rest)
    return blocks


def test_the_scan_finds_specs_and_the_cap():
    """Either one coming back empty would make every assertion below vacuously true."""
    assert _specs(), f"no Playwright specs found under {SPEC_DIR.relative_to(REPO)}"
    assert api_page_cap() > 0, "the API page cap read as zero"


@pytest.mark.parametrize("spec", [pytest.param(p, id=p.name) for p in _specs()])
def test_no_spec_requests_a_page_larger_than_the_api_allows(spec):
    cap = api_page_cap()
    offenders = [n for n in _requested_limits(_code(spec)) if n > cap]
    assert not offenders, (
        f"{spec.name} asks the API for page size(s) {sorted(set(offenders))}, and the API caps "
        f"`limit` at {cap} ({CRUD_SOURCE.relative_to(REPO)} MAX_PAGE_SIZE). The request is answered "
        f"422, so whatever the spec meant to do with that listing does not happen. Page within the "
        f"cap instead of asking past it."
    )


@pytest.mark.parametrize("spec", [pytest.param(p, id=p.name) for p in _specs()])
def test_a_cleanup_that_cannot_finish_fails_instead_of_passing_quietly(spec):
    """A suite whose cleanup silently no-ops leaves residue and reports success.

    Only specs that actually delete in `afterAll` are checked — a suite that creates nothing has
    nothing to clean and nothing to report.
    """
    for block in _after_all_blocks(_code(spec)):
        if "api.delete(" not in block and ".delete(" not in block:
            continue
        assert "throw" in block, (
            f"{spec.name}: the afterAll cleanup deletes rows but cannot fail. A listing that comes "
            f"back 422, or a DELETE refused with 403, must surface — the suite passed for its whole "
            f"life while deleting nothing, because a cleanup that removes no rows is "
            f"indistinguishable from one with no rows to remove."
        )
