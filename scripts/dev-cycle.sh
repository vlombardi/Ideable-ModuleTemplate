#!/usr/bin/env bash
# Thin dev-cycle router over the Ideable skill graph (nodes = dev states, arcs = skills).
# Delegates to scripts/common/dev_cycle.py. See rules/implementation-plan.md § Overall view
# for the canonical graph, and the docstring in dev_cycle.py for behaviour.
#
#   ./scripts/dev-cycle.sh status                    # where are we + what's next (default)
#   ./scripts/dev-cycle.sh set <NODE>                # recolour graph + set Current step / Last updated
#   ./scripts/dev-cycle.sh run                        # run current node & advance (auto-invokes agent nodes)
#   ./scripts/dev-cycle.sh run --auto-advance [N]     # chain steps: bare = until Done, N = N steps
#   ./scripts/dev-cycle.sh run --deterministic        # advance only deterministic nodes; suggest skills otherwise
#   ./scripts/dev-cycle.sh run --keep-history         # write a plan file per state transition (default: overwrite)
#
# Branch-per-plan git flow is ALWAYS ON (set DEV_CYCLE_NO_GIT=1 to disable): `run` works on the
# plan's `plan/<description>` branch, commits after each execution, and asks to merge into main
# at the Committing step (deferred when non-interactive).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/common/dev_cycle.py" "$@"
