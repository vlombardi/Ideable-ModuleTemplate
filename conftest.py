"""Repo-root pytest guard — enforce the single sanctioned test path.

The ONLY sanctioned way to run the test-and-fix step is the runner
``scripts/common/run_enabled_tests.sh`` (invoked directly or via the
``ideable-test-and-fix`` skill). It is the only path that writes the timestamped
``TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/`` artifacts maintainers rely on, and the
only run the pre-push hook will accept as evidence.

The runner exports ``IDEABLE_TEST_RUNNER=1``, which bypasses this guard. A bare ``pytest``
invocation records nothing, so it HARD-FAILS here — unless the developer explicitly opts in
with ``IDEABLE_UNRECORDED_RUN=1`` (a loud warning is printed and, again, nothing is recorded).

The opt-in is named for what it COSTS, not for how it is done. It was
``IDEABLE_ALLOW_DIRECT``, which described the mechanism — running pytest directly — and left
the consequence to be discovered: no report, so no evidence, so nothing that can gate a push,
and none of the environment the runner sets up (service URLs, e2e personas, the static-analysis
gate). "Unrecorded" is the property a reader needs at the moment they type it.

Framework-owned; force-synced to every remote module. See rules/testing-guidelines.md
§ "How tests must be run (single entry point)".
"""
import os
import sys

import pytest

_RUNNER = "IDEABLE_TEST_RUNNER"
_ALLOW = "IDEABLE_UNRECORDED_RUN"
_RENAMED_FROM = "IDEABLE_ALLOW_DIRECT"


def pytest_configure(config):
    if os.environ.get(_RUNNER) == "1":
        return  # official run via run_enabled_tests.sh — records TEST_REPORTS/
    if os.environ.get(_ALLOW) == "1":
        print(
            f"\n⚠️  pytest is running OUTSIDE the Ideable test-and-fix runner ({_ALLOW}=1).\n"
            "   Nothing is recorded: no TEST_REPORTS/ entry, so this run cannot gate a push,\n"
            "   and none of the runner's setup applies (service URLs, e2e personas, ruff/mypy/tsc).\n"
            "   Official / gate run:  ./scripts/common/run_enabled_tests.sh\n",
            file=sys.stderr,
        )
        return

    # Named explicitly rather than ignored: someone reaching for the old variable has the right
    # intent and would otherwise read the refusal below as "my opt-in did nothing".
    if os.environ.get(_RENAMED_FROM) == "1":
        raise pytest.UsageError(
            f"{_RENAMED_FROM} was renamed to {_ALLOW} — it described how the run was launched, "
            f"not what it costs.\n"
            f"    {_ALLOW}=1 pytest ...\n"
        )

    raise pytest.UsageError(
        "Ideable tests must be run through the test-and-fix runner, which records "
        "results under TEST_REPORTS/:\n"
        "    ./scripts/common/run_enabled_tests.sh\n"
        "  (or invoke the `ideable-test-and-fix` skill, which calls it).\n\n"
        "For throwaway LOCAL iteration only — nothing recorded, cannot gate a push:\n"
        f"    {_ALLOW}=1 pytest ...\n"
    )


# =================================================================================================
# `code_only` — read what the code DOES, not what a comment SAYS about it
# =================================================================================================
#
# A large family of contract tests in this repository asserts on the TEXT of a source file, because
# the property is about code that runs somewhere this suite is not (a remote module project, a
# deployed stack, a git hook). Those assertions are searches, and a search over raw source finds the
# comment that EXPLAINS a defect and reports it as the defect.
#
# That is not hypothetical and it is not rare. Five separate assertions hit it in one session:
#
#   * a check that the sync's convergence branch comes after its `unavailable` guard, defeated by a
#     comment quoting the word "Converged";
#   * a check that no code path reports a tenant as `skipped`, defeated by the comment explaining
#     why skipping was wrong;
#   * a check that a docstring's *rationale* for ignoring a read permission is not the permission
#     being consulted (`read_all_tenants` appearing in prose);
#   * two more of the same shape while `_resolve_write_tenant` and `get_entity` were sliced.
#
# Each was patched locally with its own private stripper — four near-identical `_code_only`
# helpers — which is precisely the duplication `scripts/common/container_stack_env.sh` says this
# repository has paid for four times already. So the arithmetic lives here once, in the ONE file
# every `TESTS/` directory can reach: this conftest is force-synced to every remote module project
# and its fixtures are visible to `scripts/TESTS/`, `modules/*/TESTS/` and every sub-module's
# `TESTS/` alike (a plain module at the repo root is NOT — a `TESTS/` directory with its own
# conftest gets that directory on `sys.path`, not the root).
#
# WHAT IS REMOVED, AND WHAT DELIBERATELY IS NOT.
#
# Comments and DOCSTRINGS go. Other string literals STAY, because plenty of correct assertions
# search for a message the code emits — `"TenantScope requires at least one tenant id" in auth` is
# asserting that the code says that, and stripping every string would silently break it. Docstrings
# are identified with `ast`, not a regex: a regex for triple quotes cannot tell a docstring from a
# triple-quoted SQL statement or a multi-line message, and this repository has both.

import ast as _ast
import io as _io
import textwrap as _textwrap
import tokenize as _tokenize


#: How a fragment is coaxed into parsing, and the line offset each attempt introduces.
#:
#: Callers routinely hand this ONE sliced function — `src.split("def get_entity")[1]` — which is
#: not valid Python on its own, so `ast.parse` fails and no docstring is found. That matters: the
#: docstring is usually the whole reason the caller is stripping, because it is the docstring that
#: explains the symbol the assertion is searching for. The regex this replaced handled fragments by
#: accident and would have eaten a triple-quoted SQL block; these attempts handle them on purpose.
#:
#: The shapes, in order: whole file; uniformly indented file; a slice that begins at a signature's
#: `(`, which `def _f` completes on the SAME line; a slice whose `(` was consumed by the caller's
#: `split("def name(")`, which needs the paren supplied too; and a body-only slice, which needs a
#: header line.
#:
#: Both signature-slice shapes are here because both callers exist and neither is wrong:
#: `split("def name")` leaves the `(` in the fragment, `split("def name(")` does not. Handling only
#: the first meant a docstring survived for the second — found by a test that then reported a
#: hardcoded name the code did not contain, which is the false positive this helper exists to
#: prevent.
_FRAGMENT_ATTEMPTS = (
    (lambda t: t, 0),
    (lambda t: _textwrap.dedent(t), 0),
    (lambda t: "def _f" + t, 0),
    (lambda t: "def _f(" + t, 0),
    (lambda t: "if True:\n" + t, 1),
    (lambda t: "def _f():\n" + t, 1),
)


def _parse_possibly_a_fragment(text: str):
    """(tree, line_offset) for the first attempt that parses, else (None, 0)."""
    for build, offset in _FRAGMENT_ATTEMPTS:
        try:
            return _ast.parse(build(text)), offset
        except (SyntaxError, ValueError, IndentationError):
            continue
    return None, 0


def python_code_only(text: str) -> str:
    """Python source with comments and docstrings removed; other string literals kept.

    Accepts a whole file or a FRAGMENT (one sliced function or body) — see `_FRAGMENT_ATTEMPTS`.
    A text that cannot be parsed in any of those shapes still has its comments removed.
    """
    lines = text.splitlines()
    drop: set[int] = set()

    tree, offset = _parse_possibly_a_fragment(text)

    if tree is not None:
        for node in _ast.walk(tree):
            if not isinstance(node, (_ast.Module, _ast.ClassDef, _ast.FunctionDef,
                                     _ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (isinstance(first, _ast.Expr) and isinstance(first.value, _ast.Constant)
                    and isinstance(first.value.value, str)):
                start = first.lineno - offset
                end = (first.end_lineno or first.lineno) - offset
                drop.update(range(start, end + 1))

    # Comments come out by token position, so a `#` inside a string literal is left alone.
    comment_spans: dict[int, list[int]] = {}
    try:
        for token in _tokenize.generate_tokens(_io.StringIO(text).readline):
            if token.type == _tokenize.COMMENT:
                comment_spans.setdefault(token.start[0], []).append(token.start[1])
    except (_tokenize.TokenError, IndentationError, SyntaxError):
        pass  # a fragment may not tokenize cleanly either; the docstring pass still applied

    out = []
    for number, line in enumerate(lines, 1):
        if number in drop:
            continue
        for column in sorted(comment_spans.get(number, []), reverse=True):
            line = line[:column]
        if line.strip():
            out.append(line)
    return "\n".join(out)


def shell_code_only(text: str) -> str:
    """Shell source with `#` comments removed.

    Quote-aware, because a `#` inside a string is not a comment — `BOOKKEEPING_PATHS='^(...)'` and
    `sed 's/#.*//'` both appear in this repository's scripts. A `#` starts a comment only at the
    beginning of a word, which is also why `${VAR#prefix}` and a colour literal survive.
    """
    out = []
    for line in text.splitlines():
        single = double = False
        cut = None
        for index, char in enumerate(line):
            if char == "'" and not double:
                single = not single
            elif char == '"' and not single:
                double = not double
            elif char == "#" and not single and not double:
                if index == 0 or line[index - 1] in " \t":
                    cut = index
                    break
        if cut is not None:
            line = line[:cut]
        if line.strip():
            out.append(line)
    return "\n".join(out)


def code_only_text(text: str, language: str = "python") -> str:
    """Dispatch by language. Unknown languages are a caller error, not a silent pass-through."""
    if language == "python":
        return python_code_only(text)
    if language == "shell":
        return shell_code_only(text)
    raise ValueError(
        f"code_only: unknown language {language!r}. A silent pass-through here would make an "
        f"assertion search raw source again, which is the whole thing this exists to prevent."
    )


@pytest.fixture(scope="session")
def code_only():
    """`code_only(text, language="python"|"shell")` — see the block comment above.

    A fixture rather than an import: this conftest's fixtures reach every `TESTS/` directory in the
    repository and in every remote module project, which a repo-root module does not.
    """
    return code_only_text
