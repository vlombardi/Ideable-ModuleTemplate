#!/usr/bin/env bash
# WHERE THE FRAMEWORK FILES COME FROM, stated once for the module side.
#
# `sync-template-updates.sh` fetches from it, `adopt_framework.sh` reads a release's
# `framework.lock.json` out of it before any sync can run, and `module-init.sh` sets it as a new
# project's `template` remote. Three consumers of one fact: a URL literal per script is how one of
# them quietly keeps pointing at a repository the others have moved off.
#
# The maintainer-side push uses the SSH form of the same repository, deliberately: pushing needs a
# key, fetching does not, and a remote project must never be handed a push URL it cannot use.
#
# Sourced, not executed.
IDEABLE_TEMPLATE_URL="https://github.com/vlombardi/Ideable-ModuleTemplate.git"
