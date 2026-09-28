"""A frontend must not derive permissions from the access token.

This test exists because of a shipped regression. The token became thin in the thin-token change — identity and
tenant ids, no permissions — and the module's Items page still decoded it to compute `canView`. The
set came back empty, so a fully authorized `sadmin` clicking **Items** was told "You are not
authorized to view this page."

Nothing caught it. The backend suites passed (the backend was right), and the Playwright specs that
drive the real authenticated UI are gated behind `RUN_STACK_E2E` and skipped in the gate run. So this
is a static check: it costs nothing, it always runs, and it fails the build on the exact mistake.

Scoped to every module frontend in the repo, not just this one, because every remote generated from
this template inherits the pattern.

**The module's own files are DISCOVERED, never named.** This file travels to every project generated
from `Ideable-ModuleTemplate`, where the module directory carries the module's name instead of
`module_template` and `module-init.sh` renames `TemplateItems.tsx` after the new slug. Naming either
made three of these tests `FileNotFoundError` in a remote module project the first time the CI gate
ran there — reporting the framework's own assumptions as the module's fault. The remote-safe test work.
"""
import re
from pathlib import Path

import pytest

MODULE_FRONTEND = Path(__file__).resolve().parents[1]   # modules/<THIS MODULE>/frontend
MODULE_SRC = MODULE_FRONTEND / "SOURCES" / "src"
REPO = MODULE_FRONTEND.parents[2]                       # the project root

#: The permission service is a framework contract, and its filename carries no slug, so it keeps
#: this name in every module.
PERMISSION_SERVICE = MODULE_SRC / "services" / "permissions.ts"

#: Deriving authorization from the token. `atob` alone is not enough to flag — it has legitimate
#: uses — so these look for the token being decoded *for permissions*.
_TOKEN_DERIVATION = (
    "decodeJwtPayload",
    "collectPermissionClaims",
)

_SOURCE_GLOBS = ("modules/*/frontend/SOURCES/src/**/*.ts", "modules/*/frontend/SOURCES/src/**/*.tsx")


def _frontend_sources() -> list[Path]:
    files: list[Path] = []
    for pattern in _SOURCE_GLOBS:
        files.extend(p for p in REPO.glob(pattern) if "node_modules" not in p.parts)
    return sorted(files)


#: What makes a page *gated*: it decides whether the user may see or change something. These signals
#: match the correct implementation AND the broken one this file exists to reject — a page deriving
#: `canView` from the token matches `canView`/`decodeJwtPayload` and is therefore still selected,
#: which is what stops the discovery from becoming "pages that already pass".
_GATING_SIGNALS = re.compile(
    r"fetchPermissions"
    r"|services/permissions"
    r"|useState<Set<string>"
    r"|\bcanView\b"
    r"|\bcanEdit\b"
    r"|" + r"|".join(_TOKEN_DERIVATION)
)


def _gated_pages() -> list[Path]:
    """This module's pages that decide what the user may do.

    Discovered by what a page *does*, never by a filename — `module-init.sh` renames
    `TemplateItems.tsx` after the new module's slug, so a name is the one thing that cannot be
    relied on here.
    """
    pages = sorted(p for p in MODULE_SRC.glob("pages/*.tsx") if "node_modules" not in p.parts)
    return [p for p in pages if _GATING_SIGNALS.search(p.read_text(encoding="utf-8"))]


def _gated_page_params():
    """Parametrisation over the gated pages, with an EXPLAINED skip when there are none.

    An empty parameter set would otherwise report pytest's own bare "got empty parameter set", and
    `rules/testing-guidelines.md` is explicit that a skip without a reason is an explanation-shaped
    hole where the explanation goes.
    """
    pages = _gated_pages()
    if pages:
        return [pytest.param(p, id=p.name) for p in pages]
    return [
        pytest.param(
            None,
            id="none",
            marks=pytest.mark.skip(
                reason=(
                    f"no page under {MODULE_SRC.relative_to(REPO)}/pages/ consults the permission "
                    f"service or holds a permission set, so this module gates nothing in the "
                    f"frontend and there is no positive pattern to pin. The repo-wide check that no "
                    f"frontend derives permissions from the token still runs."
                )
            ),
        )
    ]


def test_the_scan_finds_frontend_sources():
    """A glob that matches nothing would make every assertion below vacuously true."""
    files = _frontend_sources()
    assert files, "no frontend sources found — the glob has drifted"
    assert any(MODULE_SRC in p.parents for p in files), (
        f"the repo-wide scan does not reach this module's own sources ({MODULE_SRC.relative_to(REPO)})"
    )


@pytest.mark.parametrize("needle", _TOKEN_DERIVATION)
def test_no_frontend_derives_permissions_from_the_token(needle):
    offenders = [
        str(p.relative_to(REPO)) for p in _frontend_sources() if needle in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"{needle} derives authorization from the access token, which carries no permissions since "
        f"the thin-token change — the page hides itself from users who are fully authorized. Read the "
        f"permission set from host_app's /me (see services/permissions.ts). Found in: {offenders}"
    )


@pytest.mark.parametrize("page", _gated_page_params())
def test_a_gated_page_reads_the_permission_service(page):
    src = page.read_text(encoding="utf-8")
    assert "fetchPermissions" in src, (
        f"{page.name} gates on permissions without asking the permission service"
    )
    assert re.search(r"from '\.\./services/permissions'", src), (
        f"{page.name} does not import the permission service"
    )


def test_the_permission_service_calls_hostapp_me():
    src = PERMISSION_SERVICE.read_text(encoding="utf-8")
    assert "/me" in src
    assert "Authorization" in src and "Bearer" in src
    assert "decodeJwt" not in src, "the service must ASK, not decode"


@pytest.mark.parametrize("page", _gated_page_params())
def test_undetermined_permissions_are_distinct_from_none(page):
    """Otherwise the page flashes 'not authorized' on every load before the answer arrives.

    A user seeing that message is indistinguishable from a real denial, so it must not be shown while
    the answer is still in flight.
    """
    src = page.read_text(encoding="utf-8")
    assert re.search(r"useState<Set<string> \| null>\(null\)", src), (
        f"{page.name}: the permission set must start as null (undetermined), not as an empty set "
        f"(denied)"
    )
    assert "if (permissions === null) return" in src, (
        f"{page.name}: the guard must neither authorize nor deny until the permission set has arrived"
    )
