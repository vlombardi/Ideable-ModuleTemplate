# change_secrets.sh specification

## Purpose
Interactively rotate explicit secret values while preserving the structure and non-secret content of environment files.

## Contract
- Support source context (`project.env.secrets`) and deployed context (root `.env.secrets`).
- Discover enabled modules from `modules/enabled.md`; if absent, discover module directories containing env files.
- Scan the root and enabled module `.env.secrets` files for explicit literal assignments whose keys end in `_PASSWORD`, `_TOKEN`, `_SECRET`, or `_SECRET_KEY`.
- Ignore comments, empty values, variable references, and non-secret keys.
- Prompt once per secret key, show all file locations, use the current value as the default, and update every occurrence of that key.
- Enforce configured minimum secret lengths, including a minimum 50-character Authentik secret key.
- Create missing root/module secret files from their `.example` files before scanning.
- Preserve comments, unrelated assignments, and inline comments.
- Require an interactive terminal; do not silently write guessed or hardcoded values.
- Never modify config files, containers, Git history, or files outside the detected project.
