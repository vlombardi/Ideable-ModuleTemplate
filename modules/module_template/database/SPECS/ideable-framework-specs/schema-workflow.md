# Schema workflow — designing and evolving a module's datamodel

> **Status**: framework contract. Applies to every Ideable module with a backend database.

## The rule

**The model is the schema, and only Alembic writes it.**

A design tool draws, `sqlacodegen` transcribes, Alembic applies. Nothing else may create, alter or
drop a table — not the bootstrap job, not `create_all()`, not a GUI connected to a live database.

This is one sentence because it has to survive contact with a hurry. The alternative is not a
different arrangement, it is *two* owners of one schema, and two owners drift. Two documented
incidents in this repository, both silent until something broke:

- The retired `datamodel.sql` and the ORM both declared `<entity>`. The SQL file once carried four
  `au_*` audit columns; it was later edited to remove them, and every deployed database kept them
  anyway, because `CREATE TABLE IF NOT EXISTS` does not alter. The repository and the databases
  disagreed for a year and no check could see it.
- The first Alembic baseline probed one table to decide whether a database needed creating. On a
  fresh install the bootstrap had already created that table, so the probe took the adoption
  branch and the Continuum audit tables were never created at all.

Both are the same failure. Hence: one owner, and a gate that proves it.

## The two files a module keeps: schema and seed

A clean system installed from scratch is defined by exactly two things, kept apart because they
have different owners and different fates in production.

| File | Where | Applied by | In production |
|---|---|---|---|
| `database/SPECS/schema.sql` | SPECS only — never built or deployed | **nothing** — generated | migrations rule the evolution |
| `database/SPECS/seed.sql` | SPECS → DIST/initdb → `deployment_root/modules/<MODULE>/database/initdb/` | the bootstrap job, from the **mounted** copy | replaced by a restored backup |

Both are **specifications**, so both are authored in `SPECS/` — the sub-module's source of truth.
`SOURCES/` holds build inputs (and is gitignored and rebuilt for some sub-modules), `DIST/` holds
deploy artifacts. Nothing applies `schema.sql`, so it is never copied to `DIST/` at all; it exists
to be read.

**`schema.sql` is generated, never applied.** It is `scripts/dev/schema.sh schema-sql` output: the
migrations applied to an empty database and dumped. It exists so the schema of a clean install is
readable and reviewable in one place — the role `datamodel.sql` used to play — without being a
second definition that can drift from the migrations. What creates the schema on a clean system is
the baseline migration.

**`seed.sql` is authored, deployed, and mounted — never baked into an image.** Its purpose is
functional consistency: the default users, groups, profiles, tenants and reference rows without
which the system does not work or nobody can log in. Initial data is customer-specific, so a
maintainer deploying for a given customer must be able to edit
`deployment_root/modules/<MODULE>/database/initdb/seed.sql` and redeploy **without rebuilding an
image** — the same deploy-time customisation the framework already gives `config/` files and
`config/theme-override.css`. This follows the standard pipeline in `rules/general-guidelines.md`
(`SPECS → DIST → deployment_root`, mounted read-only) and its rule that volume mounts must never
reference `SOURCES/` or `DIST/`.

It must be idempotent — the bootstrap may run it again — and contain no DDL.
`validate_modules.sh` fails the build if it does.

**In production the seed is replaced by a backup.** A real deployment starts from its own data,
not from defaults, so the restore takes the seed's place and the migrations take it from there:

```
clean system   :  baseline migration  →  seed.sql (mounted)  →  running
production     :  migrations          →  restored backup     →  running
```

That is why the seed must never carry schema: on a restored production database it is not run at
all, so anything it created would simply be missing.

### The bootstrap contract: what a clean install runs, and in what order

```
database (healthy) → migrations → seed → backend
```

Every module with a database follows this, and each step has exactly one job:

| Step | Owns | Runs |
|---|---|---|
| `migrations` | all DDL | `alembic upgrade head`, one-shot, `restart: "no"` |
| `seed` | rows only | the **mounted** `seed.sql`, plus any framework rows (the audit epoch) |
| `backend` | serving traffic | after both, gated on `/startup` matching the image's revision |

**`seed.sql` is idempotent and runs on every deploy.** That is the whole rule, and it replaces
per-script bookkeeping. `module_bootstrap_execution` — the ledger of executed one-shots — remains
only for scripts that genuinely cannot be re-run; guarding an idempotent script buys nothing and
costs an order-dependent trap. That trap is not theoretical: a ledger key recorded by an earlier
release once stopped a block from re-running, and `module_runtime_meta` was simply absent at
deploy time until the block was made self-contained.

`validate_modules.sh` enforces both halves: an `INSERT` without `ON CONFLICT` or `WHERE NOT
EXISTS` fails the build, and so does a `seed.sql` that no job mounts and applies — a seed file
nothing runs is worse than none, because the rows appear to be guaranteed.

**Framework tables are declared where they are used, not everywhere.** `module_runtime_meta` holds
`system_epoch`, the reference instant for synthetic audit-creation rows, and belongs to every
module whose `audit.py` reads it. `module_bootstrap_execution` belongs only to modules that have
a non-idempotent one-shot. Creating a table nothing writes to, for symmetry, is how "the same
thing in a different shape per module" starts.

> host_app is the cautionary example. It received the audit-correctness code that reads
> `module_runtime_meta.system_epoch` but never received the table, so every read raised, was
> caught, and fell back to *now* — per process, changing on every redeploy, which is exactly the
> drift the audit-correctness work set out to remove. Nothing failed; the audit trail just quietly reported different
> creation timestamps to different users.

### host_app is a worked example of the failure this prevents

`database/SPECS/01-hostapp-schema.sql` was baked into `/docker-entrypoint-initdb.d/`, so Postgres
created `tenants`, `users`, `user_tenant_audit` and `auth_entity_mapping` on every fresh volume —
tables Alembic also owned. The two drifted exactly as predicted: those four tables hold `TEXT`
while the tables SQLAlchemy created hold `VARCHAR`, and six indexes existed that no model
declared, which the first autogenerated migration would have dropped. Baking it into the image was itself a departure from the
documented pipeline, which deploys `database/DIST/initdb/*.sql` to `deployment_root` and mounts it.
The image then shipped only `00-create-authentik-db.sh`, which created a *database* — something
Alembic cannot do, and which had to exist before anything could connect. That script is gone too
(the identity-plane review): once the identity plane got its own Postgres instance, the database it created
here was an orphan nothing connected to. **The image now bakes nothing**, and its `Dockerfile`
remains purely as the extension point for the one thing that genuinely cannot be done later:
creating a **DATABASE**, which must exist before anything can connect and which Alembic cannot
create. Nothing else belongs there — an `initdb` script runs only on an empty `PGDATA`, so
anything it provisions is absent from every database that has ever been deployed. In particular
the application role is **not** created here (§ *The application role*). Note the failure mode if
you add a script back: `COPY *.sh` with no matching file **fails the build**, so add the file and
the `COPY` together.

### For remote modules

This is the framework's **default**, and the shape Ideable recommends: schema generated from
migrations, seed authored and idempotent, production starting from a restore. A remote module's
maintainers own their module's specs and may depart from it — but the reason the default is what
it is should be weighed first, because the failure it prevents is silent and only shows up in
deployed databases, long after the repository stopped describing them.

## Phases

`scripts/dev/schema.sh` implements each phase as a subcommand. All of them work on **throwaway
databases** — `<db>_design`, `<db>_head`, `<db>_verify` — created and dropped per run in the
module's own Postgres container. The deployed database is read, never written.

### 1. Design — `schema.sh design <module>`

**In**: nothing (a new datamodel), or the current schema.
**Out**: `<db>_design`, a database the design tool may freely modify.

The command materialises the current schema by applying the committed migrations to an empty
database. It is built from the migrations rather than copied from production **on purpose**:
production may carry drift that no migration describes, and importing that drift into a design
would launder it into the next migration.

Recommended open-source tools, neither of which does the whole job (see § Tool notes):

- **ChartDB** (AGPLv3, self-hosted) — drag-and-drop; imports by pasting the output of one query,
  so the database never has to be reachable from the tool.
- **Azimutt** (MIT, self-hostable) — connects directly; design in AML with the diagram alongside.

Design **only the entity tables**. The audit tables (`*_version`, `transaction`,
`transaction_meta`) are generated by SQLAlchemy-Continuum from `__versioned__ = {}`; drawing them
by hand creates a second, conflicting definition of them.

Commit the DBML export if the tool produces one — it makes the diagram reviewable in a pull
request and diffable in git, which a screenshot never is.

### 2. Model — `schema.sh model <module>`

**In**: `<db>_design`.
**Out**: `app/models.generated.py`, a **candidate** to merge into `app/models.py`.

`sqlacodegen` transcribes the designed database into SQLAlchemy 2.0 models. It is restricted to
entity tables, because it knows nothing about Continuum and would otherwise emit explicit
`*Version` and `Transaction` classes that collide with the generated ones.

Merging is by hand and deliberately so. `sqlacodegen` drops what it cannot know:

- `__versioned__ = {}` on audited entities — re-add it.
- Singular class names — it pluralises (`<Entity>s`, not `<Entity>`).
- Every comment — including the ones explaining why a column is the way it is.

**Fast path**: for adding a column, skip phases 1–2 entirely and type the line into `models.py`.
The design path earns its keep when drawing a new module's twenty tables, not when adding a field.

### 3. Migration — `schema.sh migration <module> -m "message"`

**In**: `app/models.py` (desired) and `<db>_head` (current).
**Out**: `alembic/versions/<YYYYMMDD>_<HHMM>_<slug>.py`.

A migration is a **delta**, so generating one needs two states present at once. This is why it
cannot run against the design database: a model transcribed from `<db>_design` and diffed against
`<db>_design` agrees with itself and yields an empty migration, every time.

`<db>_head` is an empty database with the committed migrations applied — by definition "what the
migrations say the schema is". Diffing against it rather than against production also means
manual drift on production cannot silently become part of a migration.

**Review the result.** Autogenerate detects structure, never intent:

- It cannot know a column needs backfilling. Add `op.execute(...)` for the data.
- It renders a **rename** as drop + add, which loses the data. Rewrite those by hand.
- The migration **must be unconditional**. Only a baseline may branch on what exists.

Read the SQL before it runs: `alembic upgrade <previous-revision>:head --sql`.

> Offline `--sql` cannot inspect a database, so it silently skips the conditional branches in a
> baseline and emits an almost-empty script. It is for reviewing ordinary (unconditional)
> migrations, not for rendering a baseline.

### 4. Verify — `schema.sh verify <module>`

Two gates, ~4 seconds, run on every push:

1. **Fresh install** — empty database → `alembic upgrade head` → `alembic check` reports no new
   operations, and the audit tables exist. The explicit audit-table probe is there because
   `alembic check` alone did *not* catch the fresh-install bug: check compares what it can see.
2. **Data fidelity** — a copy of the deployed database → `alembic upgrade head` → row counts
   unchanged per table, and `alembic check` clean afterwards. A deployed database that adopts the
   migrations must end up matching the model, or the next autogenerate folds today's drift into
   tomorrow's migration.

`scripts/common/validate_modules.sh` enforces the same rule **statically** at build time, where no
database exists: no DDL in the bootstrap job, no DDL in `initdb/*.sql`, no `create_all()` — and,
for a tenant-scoped module, the application role (§ *The application role*).

## Migration files

Filenames are `YYYYMMDD_HHMM_<slug>.py` (`file_template` in `alembic.ini`), so `versions/` reads
as a timeline. The **order is defined by `down_revision`**, not by the filename: two developers
adding a migration on the same day would otherwise interleave in an order nobody chose, and
nothing would notice. With the link, a fork fails loudly as "multiple heads".

## Baselines and squashing

A baseline is the first migration: `down_revision = None`, describing the whole schema. It is the
**only** migration allowed to be conditional, because it must work on both an empty database and
on deployments that predate Alembic. Each table is checked independently — never infer the state
of a whole schema from one probe.

`schema.sh squash` prints the maintainer procedure for collapsing an accumulated history into a
fresh baseline. Its step 5 is not optional: every deployed database must be `alembic stamp`ed at
the new revision, or it will try to create tables it already has.

## Bootstrap and Alembic

| | owns |
|---|---|
| **Alembic** | every `CREATE`/`ALTER`/`DROP` of a **schema object** — entity tables, audit tables, framework tables, and the RLS `ENABLE`/`FORCE` and policies that sit on them |
| **Bootstrap job** | **rows** — seed data, the `system_epoch` instant, its own ledger entries — and the application **login role** with its privileges (§ *The application role*) |

Ordering in compose is therefore
`database (healthy) → migrations → bootstrap (seed + app role) → backend`.
The migrations job is one-shot with `restart: "no"`, consumed via
`service_completed_successfully` — a restarting job can never satisfy that condition.

### The application role: created by the bootstrap job, and nowhere else

`auth-specs.md` § *Two things that make RLS decorative if you get them wrong* requires the backend
to connect as a `NOSUPERUSER NOBYPASSRLS` role rather than as the owner. **That role is created by
the bootstrap job**, inside the `SYNC-MANAGED-BEGIN: bootstrap-service` block of the module's
`docker-compose.yml`. A module does not author it and must not: the block is force-synced from
`module_template`, so a bootstrap job with no `CREATE ROLE` in it is a copy that predates this
contract — running `scripts/module_only/sync-template-updates.sh` is what brings it in.

**What to expect from that sync, and what it means if you do not get it.** It rewrites the whole
`bootstrap-service` block from the template and reports the file `[updated]`. If it cannot read the
template side it reports `[UNAVAILABLE]`, refuses to print its "Converged — nothing left to align"
verdict, and exits **4** — so a run that delivered nothing cannot be mistaken for a project that was
already aligned. That mattered: the block was previously read from a filesystem path that exists
only in the maintainer's own repository, so in every remote module project the sync reported the
compose file untouched and converged while delivering nothing, and this paragraph named a command
that could not do what it said. If the sync reports `[skipped] … no SYNC-MANAGED marker for:
bootstrap-service`, the module's compose has no marker pair to replace — add
`# SYNC-MANAGED-BEGIN: bootstrap-service` / `# SYNC-MANAGED-END: bootstrap-service` around the
bootstrap service and run it again.

| | |
|---|---|
| Role name | `<PREFIX>_APP_DB_USER`, in `.env.config` — not a secret; `pg_roles` shows it to anyone who can connect |
| Password | `<PREFIX>_APP_DB_PASSWORD`, in `.env.secrets` |
| Connects as it | the backend (`DATABASE_URL`), and the isolation suite, which must prove the constraint is real |
| Connects as the owner (`<PREFIX>_ENTITIES_DB_USER`) | the database container, the migrations job, the bootstrap job — and nothing that serves a request |

What the job does, idempotently, because it runs on every deploy:

1. probe `pg_roles`, then `CREATE ROLE … LOGIN PASSWORD … NOSUPERUSER NOBYPASSRLS NOCREATEDB
   NOCREATEROLE` when absent and `ALTER ROLE` with the same attributes when present. There is no
   `CREATE ROLE IF NOT EXISTS`, and a rotated password has to land on a role that already exists.
2. `GRANT USAGE ON SCHEMA public`, then `SELECT, INSERT, UPDATE, DELETE ON ALL TABLES` and
   `USAGE, SELECT ON ALL SEQUENCES`.
3. `ALTER DEFAULT PRIVILEGES` for both — so the tables the *next* migration creates are reachable
   without anyone remembering to re-run a grant.

Step 2 is why this cannot run **before** the migrations: `ON ALL TABLES` grants on the tables that
exist at that moment. It may run **after** them because the tenant policies name no role — they
read GUCs and apply to every caller — so RLS can be forced on a table before the role it will
constrain exists.

**Not `initdb/`.** Postgres runs `/docker-entrypoint-initdb.d` **only when `PGDATA` is empty**, so
a role created there exists on a developer's fresh volume and on no database that has ever been
deployed. The symptom surfaces far from the cause — a backend that cannot log in after an upgrade
— and its obvious fix is to point `DATABASE_URL` back at the owner. That restores service and
silently makes every tenant policy decorative again, which is the one failure the role exists to
prevent.

**Not a migration.** The password comes from the deployment's `.env.secrets` and migrations are
committed to the repository. A role is a **cluster** object, not part of the schema a migration
describes: restoring a backup into a new cluster brings the tables and none of the logins. And
`CREATE ROLE` always needs the probe, while only a baseline may branch on what exists.

**Not the backend.** It connects *as* that role, so it cannot be what creates it.

**This is not a second owner of the schema.** The rule at the top of this file governs schema
objects — tables, columns, indexes, constraints, policies. Roles and privileges are the cluster's
access control: they carry a deployment secret, and they must be true *after* the last migration
and *before* the backend's first connection, which is exactly the slot the bootstrap job occupies.
`validate_modules.sh` draws the same line — it fails a bootstrap job containing `CREATE TABLE`,
`ALTER TABLE`, `DROP TABLE` or `CREATE INDEX`, while `CREATE ROLE` and `GRANT` are what it
**requires** there.

**Enforced, not merely written down.** `scripts/common/check_app_db_role.py` runs inside
`validate_modules.sh`, which `redeploy.sh` runs before any build. For a module with at least one
`__tenant_scoped__ = True` model it fails when:

- nothing in the compose file creates the role — the bootstrap block predates this contract, and
  the fix is `scripts/module_only/sync-template-updates.sh`;
- a SQL file under `database/` creates it — the `initdb` route, which skips every database that
  already has a volume;
- a long-running service's `DATABASE_URL` names the owner. One-shots (`restart: "no"`) are exempt:
  the migrations job needs DDL, and the bootstrap job is what creates the role.

A module with no tenant-scoped model is out of scope. host_app is that case — it owns the tenants
table and none of its own rows belong to a tenant, so there is no RLS there to make decorative.

Framework tables (`module_bootstrap_execution`, `module_runtime_meta`) are declared in
`app/framework_models.py`, kept apart from `models.py` because `models.py` is regenerated during
the workflow and anything in it can be overwritten. There is deliberately **no `include_object`
filter** in `alembic/env.py`: filtering a table out of autogenerate is how a second owner of the
schema gets to hide.

## Backwards compatibility: expand → migrate → contract

The backend and its database are deployed separately, so a rolling deploy runs old code against
the new schema. A migration must therefore never break the currently-running version:

1. **Expand** — add the new column nullable or with a server default. Old code ignores it.
2. **Migrate** — deploy code that writes both old and new; backfill.
3. **Contract** — in a *later* release, once no running code reads it, drop the old column.

A rename is expand + migrate + contract, never a single `ALTER ... RENAME`.

`/startup` returns 200 only when `alembic_version` matches the newest revision the image ships
(`schema_revision_matches_head()`), so a container whose code does not match the schema never
joins the load balancer.

## Tool notes

No single open-source tool covers design + reverse engineering + editing + migration generation
for PostgreSQL:

| | design | reverse-engineer | edit | migration |
|---|:--:|:--:|:--:|:--:|
| pgModeler CE (GPLv3) | ✅ | ❌ Plus only | ✅ | ❌ Plus only |
| Azimutt (MIT) | ✅ | ✅ | ✅ | ❌ |
| ChartDB (AGPLv3) | ✅ | ✅ | ✅ | ⚠️ full DDL export, LLM-based |
| DBeaver CE (Apache 2) | ⚠️ | ✅ | ⚠️ | ❌ compare is PRO |

Alembic does the last column, and does it better than a designer could: it knows about the
Continuum shadow tables. Adding `status` to `<Entity>` autogenerates *two* statements —

```python
op.add_column('<entity>', sa.Column('status', sa.String(32), server_default='draft', nullable=False))
op.add_column('<entity>_version', sa.Column('status', sa.String(32), server_default='draft', nullable=True))
```

— the second nullable, because history rows predate the column. No visual designer will ever
produce that line: the audit tables are not in the diagram. A designer-authored migration would
silently break the audit trail on every schema change.

`sqlacodegen` is a **developer tool**, not a runtime dependency — it is installed on demand by
`schema.sh model` and must not be added to the backend image.

If pgModeler's Plus edition is used, treat its `.dbm` as a drawing and never use its
diff-and-apply against a deployed database. That feature is good, and it would make pgModeler a
second thing that writes schema.
