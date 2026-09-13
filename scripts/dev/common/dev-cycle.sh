#!/usr/bin/env bash
# Thin dev-cycle router over the Ideable skill graph (nodes = dev states, arcs = skills).
# Delegates to scripts/dev/common/dev_cycle.py. See rules/implementation-plan.md § Overall view
# for the canonical graph, and the docstring in dev_cycle.py for behaviour.
#
#   ./scripts/dev/common/dev-cycle.sh status                    # where are we + what's next (default)
#   ./scripts/dev/common/dev-cycle.sh start <description>       # make that plan the active one (NotStarted only)
#   ./scripts/dev/common/dev-cycle.sh run                        # run current node & advance (auto-invokes agent nodes)
#   ./scripts/dev/common/dev-cycle.sh run --auto-advance [N]     # chain steps: bare = until Done, N = N steps
#   ./scripts/dev/common/dev-cycle.sh run --deterministic        # advance only deterministic nodes; suggest skills otherwise
#   ./scripts/dev/common/dev-cycle.sh run --keep-history         # keep every transition's plan file
#                                                     #   (default: one file, renamed `… (<state>).md` per transition)
#   ./scripts/dev/common/dev-cycle.sh pause [<description>]      # park a plan on its branch, check the target out
#   ./scripts/dev/common/dev-cycle.sh resume [<description>]     # pick a paused plan up at the node it left
#   ./scripts/dev/common/dev-cycle.sh deliver --dry-run          # compose the delivery message; change nothing
#   ./scripts/dev/common/dev-cycle.sh deliver [--target BRANCH]  # squash a Done plan onto the target and push
#
# A plan becomes the ACTIVE one by being STARTED: `start <description>` creates its
# `ACTIVE PLAN - <description>.md` link, which is the only thing the router resolves. A plan file
# with no link is work somebody wrote down, not work in hand — and because the link names the plan
# rather than one of its files, `--keep-history` no longer makes one plan look like several.
#
# `run` IS THE ONLY ADVANCE. There is no `set`: it wrote the graph and the Current step but not the
# sub-set advance, the Commit cells or the scope gate, so a plan moved by hand recorded its state
# where `run` never looked. A question only the maintainer can answer no longer needs it either —
# when one goes unanswered, `run` records `Blocked` in the plan with the question and the node to
# come back to, and the next `run` puts it again (or reads the answer written on the plan's
# `**Answer**:` line) and resumes there once every question is answered.
#
# A plan can be PAUSED: `pause` commits the tree on the plan branch, renames the plan `(Paused)`
# with the resume node still highlighted, drops the `ACTIVE PLAN` name and checks out the target.
# `resume` finds a paused plan by asking the `plan/*` branches — its file lives on its own branch,
# never in the working tree — checks that branch out and renames the plan back onto its node. Both
# take an optional <description>, so the remedy the two-plans refusal names can be aimed; bare
# `pause` is never refused and reports which plan it parked.
#
# EVERY INVOCATION IS TEED to `.ideable-work/dev-cycle.log` (append; rolls over at 5 MB; override
# the path with DEV_CYCLE_LOG, disable with DEV_CYCLE_LOG=), so a headless run can be watched with
# `tail -f` rather than reported on afterwards.
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

# EVERY RUN IS WATCHABLE. A headless run prints to a stdout nobody is looking at — the agent's tool
# calls, the runners' output, the router's own decisions — and the only account of it left was the
# driver's summary afterwards. `rules/implementation-plan.md` § *A failure must be visible* asks for
# the opposite: the maintainer should be able to watch what is happening, not be told about it.
# So the whole invocation is teed to ${DEV_CYCLE_LOG}, and `tail -f` on it follows a run nobody is
# sitting at.
#
# APPENDED, never truncated: this router's subject is signals that get lost, and a log that
# overwrites the previous run destroys the evidence of the run before the one being diagnosed.
# Growth is bounded by a rollover at 5 MB — one generation, because the reason to keep a log is the
# run you are looking at and the one before it.
#
# `2>&1` because the runners and the Agent SDK write their failures to stderr, and a log holding
# only the happy half of a run is the lying signal this whole plan removes. `pipefail` (set above)
# is what keeps the router's own exit code: without it every run would report `tee`'s success.
#
# The question prompt is NOT affected. `agent_conversation.py` reads and writes `/dev/tty`
# directly, with no fallback to stdin — so teeing stdout cannot swallow a question or the countdown
# beside it. What it does cost is tty-ness for the child processes' stdout: `redeploy.sh` and the
# test runner lose colour. Measured against the alternative of logging only headless runs, which
# would mean the log exists only when the maintainer is not there to have asked for it.
#
# `${VAR-default}` and NOT `${VAR:-default}`: the colon form treats an EMPTY value as unset, so
# `DEV_CYCLE_LOG=` — the documented way to turn logging off — would have silently fallen back to
# the default path and logged anyway. Caught by `test_logging_can_be_turned_off_without_losing_the
# _output`, which measures the default log's mtime across the call.
DEV_CYCLE_LOG="${DEV_CYCLE_LOG-${REPO}/.ideable-work/dev-cycle.log}"
if [ -n "${DEV_CYCLE_LOG}" ]; then
  mkdir -p "$(dirname "${DEV_CYCLE_LOG}")"
  if [ -f "${DEV_CYCLE_LOG}" ] && [ "$(wc -c <"${DEV_CYCLE_LOG}")" -gt 5242880 ]; then
    mv -f "${DEV_CYCLE_LOG}" "${DEV_CYCLE_LOG}.1"
  fi
  {
    printf '\n=== dev-cycle.sh %s — %s ===\n' "$*" "$(date '+%Y-%m-%d %H:%M:%S')"
  } >>"${DEV_CYCLE_LOG}"
  # `set -e` is disabled around the pipeline ON PURPOSE. With `pipefail` on, a non-zero router
  # would abort the script here and `exit "${PIPESTATUS[0]}"` — the line that preserves the real
  # exit code — would never run, turning every failing run into a bare `1` with no code of its own.
  set +e
  "$PY" "${SCRIPT_DIR}/dev_cycle.py" "$@" 2>&1 | tee -a "${DEV_CYCLE_LOG}"
  _rc="${PIPESTATUS[0]}"
  set -e
  exit "${_rc}"
fi

exec "$PY" "${SCRIPT_DIR}/dev_cycle.py" "$@"
