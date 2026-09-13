"""A remote module must send the CURRENT session's token, and must not call a failure a denial.

This file exists because of a shipped defect, and every assertion in it is one link of the chain
that defect walked:

`authToken.ts` built the sessionStorage key by stripping the authority's trailing slash, while
oidc-client-ts writes `oidc.user:${authority}:${client_id}` with the authority verbatim — and the
documented Authentik authority ends in `/`. The direct lookup therefore matched in NO deployment.
Every call fell through to a scan that returned the first `oidc.user:` entry sessionStorage yielded,
regardless of authority, client or expiry. A leftover entry from an earlier session then handed
host_app a token whose signing key Authentik no longer published; host_app answered
`401 JWT signing key not found`; `fetchPermissions` collapsed that into an empty set; and the Items
page told a fully authorized `sadmin` "You are not authorized to view this page."

Nothing caught it. The backend was right, so the backend suites passed. The live-stack Playwright
specs drive a FRESH browser context, which holds exactly one `oidc.user:` entry — so the scan
returned the right token by luck and the authorization specs went green while the defect was live in
the browser. That is the gap these checks close: they need no stack, no browser and no second
session, and they always run.

These are STATIC checks. The module frontend carries no JS test runner (no vitest/jest in
`package.json`), so adding one to assert this behaviourally would be a framework-wide dependency
change. They pin the SHAPE of the fix instead — deliberately, and the same way
`test_permission_source_contract.py` does next door.

`services/authToken.ts` and `services/permissions.ts` are framework contracts whose filenames carry
no module slug, so they keep these names in every project generated from `Ideable-ModuleTemplate`.
The gated page is DISCOVERED, never named: `module-init.sh` renames `TemplateItems.tsx` after the new
module's slug.
"""
import re
from pathlib import Path

import pytest

MODULE_FRONTEND = Path(__file__).resolve().parents[1]   # modules/<THIS MODULE>/frontend
MODULE_SRC = MODULE_FRONTEND / "SOURCES" / "src"
REPO = MODULE_FRONTEND.parents[2]                       # the project root

TOKEN_SOURCE = MODULE_SRC / "services" / "authToken.ts"
PERMISSION_SERVICE = MODULE_SRC / "services" / "permissions.ts"

#: What oidc-client-ts's `UserManager._userStoreKey` getter must still return. The module addresses
#: the stored entry by this template, so a library change here silently breaks the lookup.
EXPECTED_LIBRARY_KEY_TEMPLATE = "user:${this.settings.authority}:${this.settings.client_id}"


def _token_source() -> str:
    return TOKEN_SOURCE.read_text(encoding="utf-8")


def _oidc_client_bundle() -> Path | None:
    """The installed oidc-client-ts ESM bundle, or None when the library is not in this project.

    host_app owns the OIDC session and therefore the dependency; a remote module reads the storage
    the host wrote and depends on nothing. So this is absent by design in a remote module project,
    and the pin below skips there rather than failing the framework's own assumption as the module's
    fault.
    """
    for candidate in sorted(REPO.glob("modules/*/frontend/SOURCES/node_modules/oidc-client-ts/dist/esm/*.js")):
        return candidate
    return None


def _gated_pages() -> list[Path]:
    """This module's pages that decide what the user may see, found by what they DO, not by name."""
    return sorted(
        p
        for p in MODULE_SRC.glob("pages/*.tsx")
        if "node_modules" not in p.parts and "fetchPermissions" in p.read_text(encoding="utf-8")
    )


def _gated_page_params():
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
                    f"service, so this module renders no permission failure and there is no message "
                    f"mapping to pin. The token-source checks still run."
                )
            ),
        )
    ]


def test_the_token_source_exists():
    """A missing file would make every assertion below vacuously true."""
    assert TOKEN_SOURCE.is_file(), (
        f"{TOKEN_SOURCE.relative_to(REPO)} is missing — it is the framework contract for reading "
        f"the host's access token, and its name carries no module slug"
    )


def test_the_library_key_format_is_still_what_the_module_assumes():
    """The module hardcodes the library's key layout, so pin it to the library, not to a memory."""
    bundle = _oidc_client_bundle()
    if bundle is None:
        pytest.skip(
            "oidc-client-ts is not installed in this project — host_app owns the OIDC session and "
            "therefore the dependency, so a remote module project has nothing to pin here. The "
            "checks on this module's own token source still run."
        )
    source = bundle.read_text(encoding="utf-8")
    assert EXPECTED_LIBRARY_KEY_TEMPLATE in source, (
        f"oidc-client-ts no longer builds its user-store key as {EXPECTED_LIBRARY_KEY_TEMPLATE!r} "
        f"({bundle.relative_to(REPO)}). Every module reads that entry directly, so the new layout "
        f"must be mirrored in {TOKEN_SOURCE.relative_to(REPO)} before this pin is updated."
    )


def test_the_token_source_addresses_the_library_key_verbatim():
    src = _token_source()
    assert "'oidc.user:'" in src, (
        "the token source must address the entry oidc-client-ts wrote, whose key begins 'oidc.user:'"
    )
    assert re.search(r"\$\{OIDC_USER_KEY_PREFIX\}\$\{\w+\}:\$\{\w+\}", src), (
        "the key must be built as <prefix><authority>:<client_id> — the authority interpolated as it "
        "is, because that is the exact string oidc-client-ts stored"
    )


def test_the_token_source_tries_both_trailing_slash_forms():
    """The defect itself: only the stripped authority was ever tried, and the real key has the slash.

    The authority is read from one variable shared with host_app, but nothing guarantees which slash
    form a deployment's templating leaves in it — so BOTH have to be candidates. Requiring both makes
    the original one-form mistake impossible to reintroduce silently.
    """
    src = _token_source()
    strips_the_slash = re.search(r"replace\(/\\/\+\$/", src) or re.search(r"replace\(/\\/\$/", src)
    appends_the_slash = re.search(r"\$\{\w+\}/", src)
    assert strips_the_slash and appends_the_slash, (
        "the token source must try the authority BOTH with and without its trailing slash "
        f"(strips={bool(strips_the_slash)}, appends={bool(appends_the_slash)}). Trying only the "
        "stripped form matched no deployment at all: the documented Authentik authority ends in '/', "
        "and oidc-client-ts stores the authority verbatim."
    )


def test_the_token_source_never_returns_another_sessions_token():
    """A token from another authority or client is not a worse answer than none. It is a wrong one."""
    src = _token_source()
    assert re.search(r"if \(authority && clientId\)", src), (
        "the lookup must be guarded on knowing the current authority and client, so a known "
        "configuration is answered ONLY from that session's own key"
    )
    assert re.search(r"\.length === 1", src), (
        "when the configuration is unknown the scan must refuse to guess — exactly one unexpired "
        "candidate is the session, several are ambiguous. Returning the first of several is the "
        "original defect: it sent a leftover token whose signing key Authentik no longer published."
    )


def test_the_token_source_skips_an_expired_entry():
    src = _token_source()
    assert "expires_at" in src, (
        "an expired entry must be treated as no entry — sending its token earns a 401 that the "
        "caller downstream cannot tell apart from a permission denial"
    )


def test_the_permission_service_distinguishes_a_failure_from_a_denial():
    """An empty set arrives for three reasons, and only one of them is 'not authorized'."""
    src = PERMISSION_SERVICE.read_text(encoding="utf-8")
    assert re.search(r"status === 401", src), (
        "the permission service must recognise host_app's 401 — an invalid or expired session says "
        "nothing about what the user may do"
    )
    for outcome in ("'ok'", "'session-expired'", "'unavailable'"):
        assert outcome in src, (
            f"the permission service must report outcome {outcome}: the caller cannot otherwise tell "
            f"a real empty permission set from a session or service failure"
        )


@pytest.mark.parametrize("page", _gated_page_params())
def test_a_gated_page_denies_only_when_hostapp_actually_answered(page):
    src = page.read_text(encoding="utf-8")
    assert not re.search(r"t\(\s*'common\.notAuthorized'\s*\)", src), (
        f"{page.name} renders the denial message unconditionally. 'Not authorized' is only true when "
        f"host_app answered and the permission was genuinely absent; for an expired session or an "
        f"unavailable service it tells the user something no code here established — which is how a "
        f"stale token was reported to a fully authorized administrator as a denial."
    )
    assert "PermissionOutcome" in src, (
        f"{page.name} must consult the outcome of the permission fetch, not only the set it returned"
    )
    assert "common.notAuthorized" in src, (
        f"{page.name} must still say 'not authorized' for the outcome that licenses it — a real "
        f"denial has to remain visible and distinguishable"
    )
