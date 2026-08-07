"""Repo-root pytest guard — enforce the single sanctioned test path.

The ONLY sanctioned way to run the test-and-fix step is the runner
``scripts/common/run_enabled_tests.sh`` (invoked directly or via the
``ideable-test-and-fix`` skill). It is the only path that writes the timestamped
``TEST_REPORTS/<YYYY-MM-DD-HH-MM-SS>-<MODULE>/`` artifacts maintainers rely on.

The runner exports ``IDEABLE_TEST_RUNNER=1``, which bypasses this guard. A direct
``pytest ...`` invocation produces no report, so it HARD-FAILS here — unless the
developer explicitly opts into throwaway local iteration with ``IDEABLE_ALLOW_DIRECT=1``
(a loud warning is printed and, again, no report is written).

Framework-owned; force-synced to every remote module. See rules/testing-guidelines.md
§ "How tests must be run (single entry point)".
"""
import os
import sys

import pytest

_RUNNER = "IDEABLE_TEST_RUNNER"
_ALLOW = "IDEABLE_ALLOW_DIRECT"


def pytest_configure(config):
    if os.environ.get(_RUNNER) == "1":
        return  # official run via run_enabled_tests.sh — records TEST_REPORTS/
    if os.environ.get(_ALLOW) == "1":
        print(
            f"\n⚠️  pytest is running OUTSIDE the Ideable test-and-fix runner ({_ALLOW}=1).\n"
            "   Throwaway local iteration: NO TEST_REPORTS/ entry will be created.\n"
            "   Official / gate run:  ./scripts/common/run_enabled_tests.sh\n",
            file=sys.stderr,
        )
        return
    raise pytest.UsageError(
        "Ideable tests must be run through the test-and-fix runner, which records "
        "results under TEST_REPORTS/:\n"
        "    ./scripts/common/run_enabled_tests.sh\n"
        "  (or invoke the `ideable-test-and-fix` skill, which calls it).\n\n"
        "For throwaway LOCAL iteration only (no TEST_REPORTS/ written), opt in explicitly:\n"
        f"    {_ALLOW}=1 pytest ...\n"
    )
