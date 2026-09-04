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
#   ./scripts/dev-cycle.sh run --keep-history         # keep every transition's plan file
#                                                     #   (default: one file, renamed `… (<state>).md` per transition)
#   ./scripts/dev-cycle.sh deliver --dry-run          # compose the delivery message; change nothing
#   ./scripts/dev-cycle.sh deliver [--target BRANCH]  # squash a Done plan onto the target and push
#
# Branch-per-plan git flow is ALWAYS ON (set DEV_CYCLE_NO_GIT=1 to disable): `run` works on the
# plan's `plan/<description>` branch and commits after each execution. Nothing is merged by `run`,
# and nothing is asked at Committing: landing the work is the `deliver` action, which runs only on a
# plan at Done, squashes onto the target as ONE commit whose message is the plan's abstract, and
# deletes the plan branch.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/common/dev_cycle.py" "$@"
