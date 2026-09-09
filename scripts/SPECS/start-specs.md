# start.sh specification

## Purpose
Start all Docker Compose containers for the project.

## Contract
- Accept `-h`/`--help` and `--repull` flags.
- Source `.env.secrets` then `.env.config` from the script directory before invoking `docker compose`.
- Use `APP_SLUG` (from env) as the compose project name; fall back to the script directory basename.
- Run `docker compose up -d --remove-orphans` with `--pull missing` by default.
- When `--repull` is passed, use `--pull always` instead to force-pull all images before starting containers.
- Detect stale Authentik bootstrap state on failure and print recovery instructions.
- Print startup timing (start, finish, duration) on exit.
