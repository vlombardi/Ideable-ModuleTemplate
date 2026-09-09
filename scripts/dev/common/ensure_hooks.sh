#!/usr/bin/env bash
# Enable this repo's git hooks if they are not already enabled.
#
# `core.hooksPath` lives in `.git/config`, which is NOT part of the repository's content — git
# deliberately does not ship hooks with a clone, because cloning a repo must not give it the right
# to run code on your machine. The consequence is that a hook protects only the clone where someone
# remembered to switch it on.
#
# "Remember to run one command" is exactly the class of rule that erodes, so it is not left to
# memory: every routine entry point sources this, and the first `redeploy.sh` or test run in a fresh
# clone turns the hooks on and says so. Nothing to look up, nothing to forget.
#
# Opt out for a single command with IDEABLE_NO_HOOKS=1; disable permanently with
#   git config --unset core.hooksPath
set -uo pipefail

[[ "${IDEABLE_NO_HOOKS:-0}" == "1" ]] && exit 0
command -v git >/dev/null 2>&1 || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[[ -d "$_root/.githooks" ]] || exit 0

_current="$(git config --get core.hooksPath 2>/dev/null || true)"
if [[ "$_current" != ".githooks" ]]; then
  git config core.hooksPath .githooks
  echo "[hooks] enabled this repo's git hooks (core.hooksPath -> .githooks)."
  echo "[hooks]   .githooks/pre-push refuses a push whose code was never tested green."
  echo "[hooks]   Undo with: git config --unset core.hooksPath"
fi
exit 0
