#!/usr/bin/env bash
# Delete Traefik's acme.json cache so certificates are re-issued on next startup.
# Use ONLY when you intentionally need Traefik to request new certificates
# (e.g., after changing EXTERNAL_BASE_HOST or suspecting compromised certs).

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: ./scripts/runtime/config/reissue-certificates.sh

Deletes modules/host_app/traefik/acme.json (after confirmation) and recreates
an empty placeholder with 600 permissions. Run this ONLY when you need Traefik
and Let's Encrypt to re-issue certificates (for example after changing
EXTERNAL_BASE_HOST or if the cached certificate/private key is compromised).
Frequent resets can trigger Let's Encrypt rate limits.
EOF
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT=""
CURRENT_DIR="$SCRIPT_DIR"
for _ in $(seq 1 6); do
  if [[ -f "$CURRENT_DIR/modules/host_app/traefik/acme.json" ]]; then
    PROJECT_ROOT="$CURRENT_DIR"
    break
  fi
  CURRENT_DIR="$(cd "$CURRENT_DIR/.." && pwd)"
done

if [[ -z "$PROJECT_ROOT" ]]; then
  echo "ERROR: Could not locate modules/host_app/traefik/acme.json relative to $SCRIPT_DIR" >&2
  exit 1
fi

ACME_PATH="${PROJECT_ROOT}/modules/host_app/traefik/acme.json"
if [[ ! -e "$ACME_PATH" ]]; then
  echo "ERROR: $ACME_PATH does not exist. Nothing to reset." >&2
  exit 1
fi

echo "Traefik stores the Let's Encrypt certificates in acme.json."
echo "Removing it forces Traefik to request NEW certificates on next start."
echo "Only do this after changing domains, rotating compromised certs, or when support explicitly requests it."
echo "Frequent resets can hit Let's Encrypt rate limits and cause downtime."
read -rp "Proceed with deleting acme.json? (type 'yes' to confirm): " answer
if [[ "${answer,,}" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_PATH="${ACME_PATH}.bak-${TIMESTAMP}"
if [[ -s "$ACME_PATH" ]]; then
  cp "$ACME_PATH" "$BACKUP_PATH"
  echo "Backup created at $BACKUP_PATH"
fi

rm -f "$ACME_PATH"
touch "$ACME_PATH"
chmod 600 "$ACME_PATH"

echo "acme.json has been reset. Traefik will request new certificates on the next start."
echo "Reminder: run deployment_root/start.sh to bring the stack back up."
