#!/usr/bin/env bash
# Thin dev-cycle router over the Ideable skill graph (nodes = dev states, arcs = skills).
# Delegates to scripts/dev/common/dev_cycle.py. See rules/implementation-plan.md § Overall view
# for the canonical graph, and the docstring in dev_cycle.py for behaviour.
#
#   ./scripts/dev/common/dev-cycle.sh status                    # where are we + what's next (default)
#   ./scripts/dev/common/dev-cycle.sh set <NODE>                # recolour graph + set Current step / Last updated
#   ./scripts/dev/common/dev-cycle.sh run                        # run current node & advance (auto-invokes agent nodes)
#   ./scripts/dev/common/dev-cycle.sh run --auto-advance [N]     # chain steps: bare = until Done, N = N steps
#   ./scripts/dev/common/dev-cycle.sh run --deterministic        # advance only deterministic nodes; suggest skills otherwise
#   ./scripts/dev/common/dev-cycle.sh run --keep-history         # keep every transition's plan file
#                                                     #   (default: one file, renamed `… (<state>).md` per transition)
#   ./scripts/dev/common/dev-cycle.sh deliver --dry-run          # compose the delivery message; change nothing
#   ./scripts/dev/common/dev-cycle.sh deliver [--target BRANCH]  # squash a Done plan onto the target and push
#
# Branch-per-plan git flow is ALWAYS ON (set DEV_CYCLE_NO_GIT=1 to disable): `run` works on the
# plan's `plan/<description>` branch and commits after each execution. Nothing is merged by `run`,
# and nothing is asked at Committing: landing the work is the `deliver` action, which runs only on a
# plan at Done, squashes onto the target as ONE commit whose message is the plan's abstract, and
# deletes the plan branch.
set -euo pipefail
# WHERE THIS SCRIPT REALLY LIVES. The repo root carries a symlink to this file, and the symlink is
# how it is normally invoked (`./dev-cycle.sh`). Bash sets BASH_SOURCE[0] to the path AS INVOKED, so
# `dirname` of the link yields the repo root and the walk to `../../..` lands one level ABOVE the
# repo — silently, because `cd` succeeds on any ancestor that exists. Measured 2026-09-08 before the
# link was created. So the link is resolved first, and only then is the root computed.
#
# Resolved inline rather than sourced from a helper: finding a helper needs the resolved directory
# this block exists to produce.
_src="${BASH_SOURCE[0]}"
while [ -L "${_src}" ]; do
  _dir="$(cd -P "$(dirname "${_src}")" && pwd)"
  _src="$(readlink "${_src}")"
  case "${_src}" in /*) ;; *) _src="${_dir}/${_src}" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "${_src}")" && pwd)"
unset _src _dir

REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# WHICH interpreter, stated rather than inherited. `exec python3` took whatever the caller's shell
# resolved, so the router's behaviour depended on whether a virtualenv happened to be active: on
# 2026-09-08 the Agent SDK was installed in `.venv` and a terminal without it activated reported the
# SDK "not installed" — true of that interpreter, and useless as a diagnosis.
#
# Prefer the project venv only when it exists: inside the dev tools container there is none, and
# python3 IS the standard interpreter there. Same shape as `scripts/dev/common/verify_stack_free.sh`
# and the two master-only verifiers, for the same reason.
PY="${IDEABLE_PY:-}"
[ -n "$PY" ] || { [ -x "$REPO/.venv/bin/python" ] && PY="$REPO/.venv/bin/python" || PY="$(command -v python3)"; }
[ -x "$PY" ] || PY="$(command -v python3)"

exec "$PY" "${SCRIPT_DIR}/dev_cycle.py" "$@"
