#!/usr/bin/env bash
# The Claude subscription token, kept in the platform keystore.
#
#     ./scripts/dev/common/claude_token.sh --mint     # mint one and store it
#     ./scripts/dev/common/claude_token.sh --status   # is one stored?
#     ./scripts/dev/common/claude_token.sh --forget   # remove it
#     ./scripts/dev/common/claude_token.sh --print    # stdout — how dev-cycle.sh reads it
#
# You run `--mint` once. Nothing else is asked of you: `scripts/dev/common/dev-cycle.sh` loads the
# token from the keystore itself and `tool.sh` forwards it into the container, which is the only
# route a credential has in there (no Keychain, no mounted credentials file — see `tool.sh`).
#
# `--mint` runs `claude setup-token` ATTACHED to the terminal, because that command runs a browser
# flow and PRINTS the token at the end: piping it swallows the one thing you need to see. You copy
# what it prints and paste it at the prompt.
#
# There is no plaintext fallback. This credential is long-lived and account-wide, so with no
# keystore the script refuses and names what to install rather than writing it to a file.
set -uo pipefail

if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  echo "[claude-token] run this, do not source it — dev-cycle.sh loads the token by itself." >&2
  return 1
fi

SERVICE='ideable-claude-oauth-token'

say() { printf '[claude-token] %s\n' "$*" >&2; }

backend() {
  if [[ "$(uname -s)" == 'Darwin' ]] && command -v security >/dev/null 2>&1; then printf 'keychain'
  elif command -v secret-tool >/dev/null 2>&1; then printf 'secret-tool'
  else printf 'none'; fi
}

load() {
  case "$(backend)" in
    keychain)    security find-generic-password -a "$USER" -s "$SERVICE" -w 2>/dev/null ;;
    secret-tool) secret-tool lookup service "$SERVICE" account "$USER" 2>/dev/null ;;
    *)           return 2 ;;
  esac
}

save() {
  case "$(backend)" in
    # -U updates in place, so re-minting a rotated token is the same command as the first one.
    keychain)    security add-generic-password -a "$USER" -s "$SERVICE" -w "$1" -U ;;
    secret-tool) printf '%s' "$1" | secret-tool store --label="$SERVICE" service "$SERVICE" account "$USER" ;;
    *)           say 'no keystore here. macOS has `security`; on Linux install `secret-tool` (libsecret).'
                 return 2 ;;
  esac
}

# Described, never shown: enough to tell two tokens apart, not enough to use.
fingerprint() { printf '%d chars, ending %s' "${#1}" "${1: -4}"; }

case "${1:---status}" in
  --mint)
    command -v claude >/dev/null 2>&1 || { say 'no `claude` on PATH (npm install -g @anthropic-ai/claude-code).'; exit 2; }
    say 'running `claude setup-token` — finish the browser flow; the token is PRINTED at the end.'
    claude setup-token || { say 'setup-token did not complete — nothing stored.'; exit 1; }
    read -rs -p '[claude-token] paste the token printed above: ' token < /dev/tty; printf '\n' >&2
    token="${token//[$'\t\r\n ']/}"
    [[ -n "$token" ]] || { say 'nothing pasted — nothing stored.'; exit 1; }
    save "$token" || exit 2
    say "stored ($(fingerprint "$token")). ./dev-cycle.sh run --auto-invoke will pick it up."
    ;;
  --status)
    if t="$(load)" && [[ -n "$t" ]]; then say "stored ($(fingerprint "$t")) — nothing else to do."
    else say 'nothing stored. Run: ./scripts/dev/common/claude_token.sh --mint'; exit 1; fi
    ;;
  --print)
    t="$(load)" && [[ -n "$t" ]] || exit 1
    printf '%s\n' "$t"
    ;;
  --forget)
    case "$(backend)" in
      keychain)    security delete-generic-password -a "$USER" -s "$SERVICE" >/dev/null 2>&1 ;;
      secret-tool) secret-tool clear service "$SERVICE" account "$USER" ;;
      *)           false ;;
    esac && say 'removed.' || { say 'nothing to remove.'; exit 1; }
    ;;
  *)
    say "unknown action: $1 — use --mint, --status, --print or --forget."
    exit 64
    ;;
esac
