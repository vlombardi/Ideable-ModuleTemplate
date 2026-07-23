# Infrastructure File List

This file is the canonical manifest of files and folders that the module_template export/sync scripts treat as infrastructure and keep aligned across remote modules.

If `scripts/module_only/sync-template-updates.sh` or `scripts/master_only/push-updates-to-module_template-repo.sh` changes this set, this manifest MUST be updated in the same change set.

## Repo-root infrastructure files

- `AGENTS.md`
- `CLAUDE.md`
- `IDEABLE-README.md`
- `.gitignore`
- `project.env.config.example`
- `project.env.secrets.example`
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

- `modules/*/.env.config`
- `modules/*/.env.config.example`
- `modules/*/.env.secrets`
- `modules/*/.env.secrets.example`
- `modules/host_app/.env.config`
- `modules/host_app/.env.config.example`
- `modules/host_app/.env.secrets`
- `modules/host_app/.env.secrets.example`
- `modules/host_app/module.json`
- `modules/host_app/docker-compose.yml`
- `modules/host_app/config/`

## Shared framework-spec files

- `modules/module_template/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/auth-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/audit-trail-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/module-integration-specs.md`
- `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md`
- `modules/module_template/backend/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/backend/SPECS/ideable-framework-specs/shared-backend-bug-avoider.md`
- `modules/module_template/database/SPECS/ideable-framework-specs/base-specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/base_specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-ui-widgets-specs.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/shared-frontend-bug-avoider.md`
- `modules/module_template/frontend/SPECS/ideable-framework-specs/framework-css-classes-reference.md`

## Design References (not part of current implementation spec chain)

The following files live in `SPECS/` but are **not** distributed as implemented framework specs.
They record design explorations or future work that has not yet been promoted into the active chain.

- `modules/module_template/SPECS/ideable-framework-specs/access-log-audit-trail.md` — design reference
  for a potential standalone Audit Service (OIDC back-channel logout, webhook ingestion). Pending
  evaluation as part of the Access Log Audit Trail refactoring.

## Notes

- Repo-root `README.md` is intentionally not included here; it is treated as custom per-module content.
- Module-level `modules/<module_name>/README.md` is intentionally not included here; it is also treated as custom per-module content.
- Branding files are not listed here because they are only synced when explicitly requested with `--all`.
