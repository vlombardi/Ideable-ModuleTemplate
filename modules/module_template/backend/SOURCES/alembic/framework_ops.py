"""Framework DDL as named, reversible Alembic operations.

Adding an entity means repeating eight pieces of DDL that autogenerate does not write. Until now
each was an `op.execute("…")` string copied between migrations, which has three costs: the SQL is
re-typed (and mis-typed) per entity, a reviewer reads raw SQL instead of intent, and **downgrades
have to be written by hand** — so most were not written at all.

These turn the same DDL into `op.enable_rls()`, `op.create_tenant_policies()` and
`op.create_hypertable()`, each with a `reverse()`. Registration uses Alembic's documented plugin
API (`@Operations.register_operation` + `@Operations.implementation_for`), verified present in the
version this project pins, **1.13.1** — the 1.18+ `Plugin` entry-point class is not needed and is
not used.

Registering an operation buys **no autogenerate coverage on its own**: that is `env.py`'s
`Rewriter`, which emits these calls into a generated migration. This module is what makes the calls
exist and be reversible; the Rewriter is what makes them appear.

Import it from `env.py` **and** from any migration that calls the ops, because registration must
happen before `MigrationContext.run_migrations()` and a migration may be run by tooling that never
imported `env.py`:

    from alembic import op
    import framework_ops  # noqa: F401  — registers op.enable_rls() and friends
"""
from __future__ import annotations

from alembic.autogenerate import renderers
from alembic.operations import MigrateOperation, Operations

#: Kept beside the DDL rather than passed at every call site: a module that partitions its audit
#: tables by a different interval is making a deliberate choice and should say so once.
DEFAULT_CHUNK_INTERVAL = "7 days"


# --------------------------------------------------------------------------------------------
# Row-level security
# --------------------------------------------------------------------------------------------
@Operations.register_operation("enable_rls")
class EnableRLSOp(MigrateOperation):
    """`ENABLE` **and** `FORCE` row level security on a table.

    Both, always, and that is the point of having one operation for it. `ENABLE` alone leaves the
    table **owner** exempt from every policy — and on a fresh install the application role IS the
    owner, so a table with ENABLE and no FORCE is a table with no isolation at all, which reads as
    protected in every review.
    """

    def __init__(self, table: str, schema: str | None = None):
        self.table = table
        self.schema = schema

    @classmethod
    def enable_rls(cls, operations, table: str, **kw):
        return operations.invoke(cls(table, **kw))

    def reverse(self):
        return DisableRLSOp(self.table, self.schema)


@Operations.register_operation("disable_rls")
class DisableRLSOp(MigrateOperation):
    def __init__(self, table: str, schema: str | None = None):
        self.table = table
        self.schema = schema

    @classmethod
    def disable_rls(cls, operations, table: str, **kw):
        return operations.invoke(cls(table, **kw))

    def reverse(self):
        return EnableRLSOp(self.table, self.schema)


def _q(op: MigrateOperation) -> str:
    return f"{op.schema}.{op.table}" if getattr(op, "schema", None) else op.table


@Operations.implementation_for(EnableRLSOp)
def _enable_rls(operations, operation):
    t = _q(operation)
    operations.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    operations.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


@Operations.implementation_for(DisableRLSOp)
def _disable_rls(operations, operation):
    t = _q(operation)
    operations.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    operations.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")


# --------------------------------------------------------------------------------------------
# Tenancy policies
# --------------------------------------------------------------------------------------------
@Operations.register_operation("create_tenant_policies")
class CreateTenantPoliciesOp(MigrateOperation):
    """The pair of policies a tenant-scoped table needs — never one without the other.

    `tenant_isolation` restricts every statement to the caller's tenants. `tenant_cross_read` is a
    SELECT-only widening, gated on a separate GUC, for the explicitly-granted cross-tenant reader.

    They are one operation because the failure modes of writing one alone are opposite and both
    bad: isolation without cross-read blocks a legitimately-authorised reader, and cross-read
    without isolation is a table with a widening and nothing to widen *from*.

    The predicates read GUCs (`app.tenant_ids`, `app.cross_tenant_read`) set per transaction by
    `crud.apply_tenant_guc`. `current_setting(…, TRUE)` returns NULL rather than erroring when
    unset, so an unscoped session matches no rows — it fails CLOSED.
    """

    def __init__(self, table: str, schema: str | None = None,
                 tenant_column: str = "tenant_id",
                 tenant_guc: str = "app.tenant_ids",
                 cross_read_guc: str = "app.cross_tenant_read"):
        self.table = table
        self.schema = schema
        self.tenant_column = tenant_column
        self.tenant_guc = tenant_guc
        self.cross_read_guc = cross_read_guc

    @classmethod
    def create_tenant_policies(cls, operations, table: str, **kw):
        return operations.invoke(cls(table, **kw))

    def reverse(self):
        return DropTenantPoliciesOp(self.table, self.schema)


@Operations.register_operation("drop_tenant_policies")
class DropTenantPoliciesOp(MigrateOperation):
    def __init__(self, table: str, schema: str | None = None):
        self.table = table
        self.schema = schema

    @classmethod
    def drop_tenant_policies(cls, operations, table: str, **kw):
        return operations.invoke(cls(table, **kw))

    def reverse(self):
        return CreateTenantPoliciesOp(self.table, self.schema)


@Operations.implementation_for(CreateTenantPoliciesOp)
def _create_tenant_policies(operations, operation):
    t = _q(operation)
    col, guc, cross = operation.tenant_column, operation.tenant_guc, operation.cross_read_guc
    operations.execute(
        f"CREATE POLICY tenant_isolation ON {t} "
        f"USING ({col} = ANY (string_to_array(current_setting('{guc}', TRUE), ',')::int[]))"
    )
    operations.execute(
        f"CREATE POLICY tenant_cross_read ON {t} FOR SELECT "
        f"USING (current_setting('{cross}', TRUE) = 'on')"
    )


@Operations.implementation_for(DropTenantPoliciesOp)
def _drop_tenant_policies(operations, operation):
    t = _q(operation)
    operations.execute(f"DROP POLICY IF EXISTS tenant_cross_read ON {t}")
    operations.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")


# --------------------------------------------------------------------------------------------
# TimescaleDB
# --------------------------------------------------------------------------------------------
@Operations.register_operation("create_hypertable")
class CreateHypertableOp(MigrateOperation):
    """Convert a table to a TimescaleDB hypertable.

    `if_not_exists` makes it idempotent; `migrate_data` covers rows written between the CREATE
    TABLE and this call.

    **There is no reverse.** TimescaleDB offers no "un-hypertable" — the only way back is to copy
    the data into a fresh plain table and swap. So `reverse()` raises rather than pretending, which
    is the honest failure: a downgrade that silently left a hypertable in place would hand back a
    database that is not the one the previous revision described.
    """

    def __init__(self, table: str, time_column: str = "issued_at",
                 chunk_interval: str = DEFAULT_CHUNK_INTERVAL, schema: str | None = None):
        self.table = table
        self.time_column = time_column
        self.chunk_interval = chunk_interval
        self.schema = schema

    @classmethod
    def create_hypertable(cls, operations, table: str, **kw):
        return operations.invoke(cls(table, **kw))

    def reverse(self):
        raise NotImplementedError(
            f"create_hypertable('{self.table}') cannot be reversed: TimescaleDB has no "
            f"un-hypertable operation. Write the downgrade by hand — copy into a plain table and "
            f"swap — or drop the table if the revision created it."
        )


@Operations.implementation_for(CreateHypertableOp)
def _create_hypertable(operations, operation):
    operations.execute(
        f"SELECT create_hypertable('{_q(operation)}', '{operation.time_column}', "
        f"chunk_time_interval => INTERVAL '{operation.chunk_interval}', "
        f"migrate_data => true, if_not_exists => true)"
    )


# --------------------------------------------------------------------------------------------
# Renderers — how autogenerate writes these ops INTO a migration file
# --------------------------------------------------------------------------------------------
# Automating a non-core DDL object is a two-part job and the second part is easy to miss: a
# comparison function decides that an op is needed, and a SEPARATE renderer turns that op into the
# Python text written into the file. Without a renderer the Rewriter in env.py can produce a
# perfectly correct directive that autogenerate then cannot write down.
@renderers.dispatch_for(EnableRLSOp)
def _render_enable_rls(autogen_context, op):
    return f"op.enable_rls({op.table!r})"


@renderers.dispatch_for(DisableRLSOp)
def _render_disable_rls(autogen_context, op):
    return f"op.disable_rls({op.table!r})"


@renderers.dispatch_for(CreateTenantPoliciesOp)
def _render_create_tenant_policies(autogen_context, op):
    return f"op.create_tenant_policies({op.table!r})"


@renderers.dispatch_for(DropTenantPoliciesOp)
def _render_drop_tenant_policies(autogen_context, op):
    return f"op.drop_tenant_policies({op.table!r})"


@renderers.dispatch_for(CreateHypertableOp)
def _render_create_hypertable(autogen_context, op):
    return (f"op.create_hypertable({op.table!r}, time_column={op.time_column!r}, "
            f"chunk_interval={op.chunk_interval!r})")
