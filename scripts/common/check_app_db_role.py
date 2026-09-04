#!/usr/bin/env python3
"""The application DB role gate: a tenant-scoped module must have one, and must use it.

Row-Level Security is the layer that still holds when a query forgets its `tenant_id` filter, and
it cannot constrain a superuser: Postgres exempts them unconditionally. So a module whose rows
belong to tenants needs a restricted `NOSUPERUSER NOBYPASSRLS` role, created by the bootstrap job,
and its backend has to actually connect as it.

Both halves fail **silently in production**, which is why this is a build-time gate:

- The role provisioned by an `initdb` script exists on a developer's fresh volume and on no
  database that has ever been deployed — Postgres runs `/docker-entrypoint-initdb.d` only when
  `PGDATA` is empty. The symptom arrives much later as a backend that cannot log in, and its
  obvious fix is to point `DATABASE_URL` back at the owner.
- A backend connecting as the owner works perfectly. Every policy is decorative and nothing says
  so: a session set to tenant 1 returns tenant 2's rows, exactly as measured when this was found.

Contract:
`modules/module_template/database/SPECS/ideable-framework-specs/schema-workflow.md`
§ *The application role*.

Offline and static — it reads `models.py`, the compose file and the module's SQL. No database.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The tenancy gate (`check_tenancy_markers.py`) rejects a non-literal declaration, so by the time
# this runs the marker is always a bare `True` or `False` and a regex reads it correctly.
_SCOPED = re.compile(r"__tenant_scoped__\s*=\s*True\b")
_CREATE_ROLE = re.compile(r"\bCREATE\s+ROLE\b", re.I)
#: `DATABASE_URL=postgresql://${<PREFIX>_ENTITIES_DB_USER}:…` — connecting as the owner.
_OWNER_URL = re.compile(r"DATABASE_URL=postgresql://\$\{[A-Z0-9_]*ENTITIES_DB_USER\}")
_BOOTSTRAP_BLOCK = re.compile(
    r"# SYNC-MANAGED-BEGIN: bootstrap-service(.*?)# SYNC-MANAGED-END: bootstrap-service", re.S)


def is_tenant_scoped(app_dir: Path) -> bool:
    """True when any model in the module declares itself tenant-scoped."""
    return any(_SCOPED.search(p.read_text(encoding="utf-8", errors="replace"))
               for p in sorted(app_dir.rglob("*.py"))) if app_dir.is_dir() else False


def role_is_created(compose_text: str) -> bool:
    """The bootstrap job must create the role.

    Scoped to the sync-managed block when it is there, because that block is the framework's own
    and is where the statement belongs; a module that organises its compose differently is still
    accepted as long as some service creates the role.
    """
    block = _BOOTSTRAP_BLOCK.search(compose_text)
    return bool(_CREATE_ROLE.search(block.group(1) if block else compose_text))


def sql_files_creating_the_role(module_dir: Path) -> list[str]:
    """Every SQL file under `database/` that creates a role — the route that skips live volumes."""
    found = []
    for path in sorted((module_dir / "database").rglob("*.sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"--[^\n]*", "", text)  # a commented-out example is not a statement
        if _CREATE_ROLE.search(text):
            found.append(str(path.relative_to(module_dir)))
    return found


def services_connecting_as_the_owner(compose_text: str) -> list[str]:
    """Long-running services whose `DATABASE_URL` names the owner.

    A one-shot keeps the owner on purpose — migrations need DDL, and the bootstrap job creates the
    role in the first place. `restart: "no"` is what makes a service one, and both already carry it
    out of necessity: they are consumed via `service_completed_successfully`, which a restarting
    job can never satisfy.
    """
    try:
        import yaml  # type: ignore
    except Exception:
        # No yaml: read the text with the one-shot blocks cut out by their sync markers.
        stripped = re.sub(
            r"# SYNC-MANAGED-BEGIN: (migrations-job|bootstrap-service).*?"
            r"# SYNC-MANAGED-END: \1", "", compose_text, flags=re.S)
        return [line.strip()[:90] for line in stripped.splitlines() if _OWNER_URL.search(line)]

    services = (yaml.safe_load(compose_text) or {}).get("services") or {}
    offenders = []
    for name, svc in services.items():
        if not isinstance(svc, dict) or str(svc.get("restart", "")).lower() == "no":
            continue
        env = svc.get("environment") or []
        entries = ([f"{k}={v}" for k, v in env.items()] if isinstance(env, dict)
                   else [str(e) for e in env])
        offenders += [f"{name}: {e[:80]}" for e in entries if _OWNER_URL.search(e)]
    return offenders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module_dir")
    parser.add_argument("--module", default="")
    args = parser.parse_args(argv)

    module_dir = Path(args.module_dir)
    tag = f"[{args.module}] " if args.module else ""
    compose = module_dir / "docker-compose.yml"

    if not compose.is_file() or not is_tenant_scoped(module_dir / "backend" / "SOURCES" / "app"):
        return 0  # no rows belong to a tenant here, so there is nothing for RLS to protect

    compose_text = compose.read_text(encoding="utf-8")
    failed = False

    if not role_is_created(compose_text):
        print(f"ERROR: {tag}nothing creates the application DB role.\n"
              "       The bootstrap job owns it, after the migrations and before the backend.\n"
              "       If this module's bootstrap block predates the contract, run\n"
              "       scripts/module_only/sync-template-updates.sh.", file=sys.stderr)
        failed = True

    for path in sql_files_creating_the_role(module_dir):
        print(f"ERROR: {tag}{path} creates a role.\n"
              "       An initdb script runs only on an empty PGDATA, so the role would be absent\n"
              "       from every database that has ever been deployed. The bootstrap job creates\n"
              "       it, on every deploy.", file=sys.stderr)
        failed = True

    for offender in services_connecting_as_the_owner(compose_text):
        print(f"ERROR: {tag}a long-running service connects as the database owner:\n"
              f"         {offender}\n"
              "       Superusers bypass Row-Level Security unconditionally, so every tenant\n"
              "       policy on this module would be decorative. Point DATABASE_URL at\n"
              "       <PREFIX>_APP_DB_USER; only the one-shot migrations job keeps the owner.",
              file=sys.stderr)
        failed = True

    if failed:
        print("       Contract: modules/module_template/database/SPECS/"
              "ideable-framework-specs/schema-workflow.md § The application role", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
