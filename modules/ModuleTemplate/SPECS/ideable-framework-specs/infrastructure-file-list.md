# Infrastructure File List

This file is the canonical manifest of files and folders that the ModuleTemplate export/sync scripts treat as infrastructure and keep aligned across remote modules.

If `scripts/module_only/sync-template-updates.sh` or `scripts/master_only/push-updates-to-ModuleTemplate-repo.sh` changes this set, this manifest MUST be updated in the same change set.

## Repo-root infrastructure files

- `AGENTS.md`
- `CLAUDE.md`
- `IDEABLE-README.md`
- `MODULE-README.md`
- `.gitignore`
- `project.env.example`
- `redeploy.sh`
- `start.sh`
- `stop.sh`
- `status.sh`
- `update_backend.sh`
- `update_frontend.sh`

## Repo-root infrastructure folders

- `.agents/`
- `.kiro/`
- `.claude/`
- `.devin/`
- `rules/`
- `scripts/`

## Module-scoped infrastructure files

- `modules/*/.env`
- `modules/*/.env.example`
- `modules/HostApp/.env`
- `modules/HostApp/.env.example`
- `modules/HostApp/module.json`
- `modules/HostApp/docker-compose.yml`
- `modules/HostApp/config/`

## Shared framework-spec files

- `modules/ModuleTemplate/SPECS/ideable-framework-specs/base-specs.md`
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/auth-specs.md`
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/audit-trail-specs.md`
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/module-integration-specs.md`
- `modules/ModuleTemplate/SPECS/ideable-framework-specs/infrastructure-file-list.md`
- `modules/ModuleTemplate/backend/SPECS/ideable-framework-specs/base-specs.md`
- `modules/ModuleTemplate/database/SPECS/ideable-framework-specs/base-specs.md`
- `modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/base_specs.md`
- `modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md`
- `modules/ModuleTemplate/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`

## Design References (not part of current implementation spec chain)

The following files live in `SPECS/` but are **not** distributed as implemented framework specs.
They record design explorations or future work that has not yet been promoted into the active chain.

- `modules/ModuleTemplate/SPECS/ideable-framework-specs/access-log-audit-trail.md` — design reference
  for a potential standalone Audit Service (OIDC back-channel logout, webhook ingestion). Pending
  evaluation as part of the Access Log Audit Trail refactoring.

## Notes

- Repo-root `README.md` is intentionally not included here; it is treated as custom per-module content.
- Module-level `modules/<module_name>/README.md` is intentionally not included here; it is also treated as custom per-module content.
- Branding files are not listed here because they are only synced when explicitly requested with `--all`.
