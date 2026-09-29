"""One router per declared entity, generated from its descriptor.

WHY GENERATED PER ENTITY AND NOT MOUNTED ONCE AT `/{entity}`. A single path segment would collapse
the OpenAPI schema to one path with one request and one response model for every entity, so the
generated client and the API docs stop being usable and the frontend loses its types. Generating a
concrete router per entity costs nothing at runtime — it happens once, at import — and every
endpoint keeps its real schemas. The parametric part is the HANDLER, which is where the duplication
was; the route being concrete is what keeps the contract readable.

WHAT A MODULE GETS WITHOUT ASKING. Every registered entity is mounted, unconditionally: there is no
mode to declare and nothing to opt into. Six endpoints per entity —

    GET    /<key>                list, filtered/sorted/paged
    GET    /<key>/{id}           one row, or 404
    POST   /<key>                create
    PUT    /<key>/{id}           update
    DELETE /<key>/{id}           delete
    GET    /<key>/{id}/history   audit trail, when the descriptor declares a version schema

— each wired to `<slug>.<permission_resource>:view` or `:edit`, and to the caller's tenant scope.
What a maintainer chooses is whether to CALL these, not whether they exist.

THE QUERY PARAMETERS ARE THE ENTITY'S OWN. The list endpoint's filters are built from the model's
`__filterable__` whitelist, so they appear in the OpenAPI schema by name and an unlisted column is
rejected before it reaches SQL. The whitelist is the entity's declaration, not a guess made here.
"""
# NO `from __future__ import annotations` IN THIS MODULE, deliberately.
#
# The generated handlers annotate their payloads with a schema taken from the descriptor
# (`payload: descriptor.create_schema`). That annotation has to be EVALUATED at definition time so
# it resolves, through the closure, to the real pydantic class. With postponed evaluation it stays
# the string "descriptor.create_schema", which pydantic then tries to resolve at module scope where
# no `descriptor` exists — and the app dies at import with
# `PydanticUndefinedAnnotation: name 'descriptor' is not defined`. Measured: the container came up
# unhealthy and the deploy failed, which is the only place this shows.
import inspect
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy_continuum import version_class

from . import query as crud
from .entities import (all_entity_descriptors, create_entity_row, delete_entity_row, get_entity_row,
                       list_entity, update_entity_row)
from .tenancy import TenantScope

logger = logging.getLogger(__name__)

#: The permission a history endpoint checks, for every entity. Audit access is one decision per
#: module, not one per entity — `authorization.yaml` declares it exactly once.
AUDIT_PERMISSION_RESOURCE = 'audit_trail'


def permission_for(platform, descriptor, action: str) -> str:
    """`<module_slug>.<resource>:<action>`.

    The slug comes from the platform and the resource from the descriptor, because the slug is a
    property of the deployment and the resource is a property of the entity.
    """
    return f'{platform.module_slug}.{descriptor.permission_resource}:{action}'


def _page(rows, total, total_is_exact, skip, limit) -> dict:
    """The page envelope every list endpoint returns.

    `next_after_id` is derived rather than queried: a full page implies there may be another, a
    short page is the end. Asking the database "is there more?" would be a second round trip for
    something the page already tells us.
    """
    return {
        'items': rows,
        'total': total,
        'total_is_exact': total_is_exact,
        'next_after_id': rows[-1].id if rows and len(rows) == limit else None,
        'page': (skip // limit) + 1 if limit > 0 else 1,
        'size': limit,
        'pages': (total + limit - 1) // limit if limit > 0 else 1,
    }


def _filter_parameters(descriptor) -> list[inspect.Parameter]:
    """One optional query parameter per filterable column, so OpenAPI names them.

    A generic `filters: dict` would have been less code and a worse contract: a caller could not
    see which columns are filterable without reading the source, and the schema would say nothing.
    """
    return [
        inspect.Parameter(
            column, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Optional[str],
        )
        for column in getattr(descriptor.model, '__filterable__', ())
    ]


def entity_descriptor_payload(descriptor) -> dict:
    """What is QUERYABLE about an entity, for a frontend to build a table from.

    The split is deliberate and stated in the plan: the backend owns what can be filtered, sorted
    and paged, because it is the side that enforces it; the frontend owns how a column is labelled
    and rendered, because a label needs translating and a cell may need arbitrary React. A payload
    carrying labels would be a second source of truth for something the frontend must own anyway,
    and a frontend copy of the whitelist drifts silently into a 422.
    """
    model = descriptor.model
    return {
        'key': descriptor.key,
        'permission_resource': descriptor.permission_resource,
        # `id` first, and it is not in `__filterable__` by design: the list endpoint takes it as
        # its own parameter rather than as a text filter, so the model's whitelist — which governs
        # LIKE filtering — does not name it. A frontend building a filter row still needs it, and
        # leaving it out shifted every column's filter input by one.
        'filterable': ['id', *getattr(model, '__filterable__', ())],
        'sortable': list(getattr(model, '__sortable__', ())),
        'versioned': descriptor.version_schema is not None,
        'read_only': descriptor.read_only,
        'max_page_size': crud.MAX_PAGE_SIZE,
        # The read schema's field names, in declaration order: the columns a row actually carries,
        # so a frontend that renders every column by default needs no second list to maintain.
        'fields': list(descriptor.read_schema.model_fields.keys()),
    }


def build_descriptor_router(platform) -> APIRouter:
    """`GET /entities` and `GET /entities/{key}` — what this module declares.

    Unauthenticated reads would leak the shape of the datamodel, so both require a caller with a
    tenant scope where the module has one to ask for; the per-entity route additionally requires
    that entity's own view permission, because being told an entity exists is already information
    about it. A module with no tenant-scoped entity at all (no `Platform.require_tenant_scope`)
    has nothing to check here beyond that permission — see `build_entity_router`'s docstring for
    why this is decided per entity and not per module.
    """
    router = APIRouter(tags=['entities'])
    list_scope_dependency = (Depends(platform.require_tenant_scope())
                             if platform.require_tenant_scope is not None
                             else Depends(lambda: None))

    def list_descriptors(scope: Optional[TenantScope] = list_scope_dependency):
        return {'entities': [entity_descriptor_payload(d)
                             for d in all_entity_descriptors().values()]}

    router.add_api_route('/entities', list_descriptors, methods=['GET'],
                         summary='What entities this module declares')
    return router


def build_entity_router(descriptor, platform) -> APIRouter:
    """The six endpoints for one entity, closed over its descriptor and the module's platform."""
    key = descriptor.key
    router = APIRouter(tags=[key])
    # Bound once here, read per request by FastAPI: these are the module's own answers (how it
    # opens a session, checks a permission, resolves a scope), not the framework's.
    get_db = platform.get_db
    view = Depends(platform.require_permission(permission_for(platform, descriptor, 'view')))
    edit = Depends(platform.require_permission(permission_for(platform, descriptor, 'edit')))
    filterable = tuple(getattr(descriptor.model, '__filterable__', ()))

    # Whether THIS entity needs a tenant scope is its own declaration, never the module's: a
    # module may have some entities tenant-scoped and others global (host_app's `tenants` and
    # `permissions` today, alongside `users` once it becomes tenant-bound — its own plan, not
    # this one). A tenant-scoped entity with no answer from the platform is a startup error, not
    # a request that runs unscoped — the alternative this guards against is measured: it is
    # exactly how the write path forgot the check the read path already had.
    tenant_scoped = getattr(descriptor.model, '__tenant_scoped__', False)
    if tenant_scoped:
        if platform.require_tenant_scope is None:
            raise RuntimeError(
                f"entity '{key}' is tenant-scoped (__tenant_scoped__ = True) but this module's "
                f"Platform has no require_tenant_scope — a tenant-scoped entity cannot be mounted "
                f"without one"
            )
        scope_dependency = Depends(platform.require_tenant_scope())
    else:
        # No dependency to resolve: a global entity's caller need not hold any tenant at all, and
        # host_app has none to offer today. `Depends` still wraps it so every handler below reads
        # `scope` uniformly, whichever branch built it.
        scope_dependency = Depends(lambda: None)

    def list_rows(
        *,
        skip: int = 0,
        # Capped at the API boundary so an oversized page is a 422 with a reason rather than a
        # giant response. `le` puts the bound in the schema, so a client sees it before sending.
        limit: int = Query(100, ge=1, le=crud.MAX_PAGE_SIZE),
        id: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        after_id: Optional[int] = None,
        include_total: bool = True,
        # Underscored: these are dependencies, not query parameters, and the filterable columns share
        # this signature under their own names — a column called `scope` (host_app's roles and
        # profiles, their owner) or `db` must not collide with them.
        _db: Session = Depends(get_db),
        _: str = view,
        _tenant_scope: Optional[TenantScope] = scope_dependency,
        **filters: Any,
    ):
        try:
            # Through the descriptor, like every other path: the eager-load plan AND the entity's own
            # `scope_query` apply here. Calling the query core directly left `scope_query` inert on
            # the one route that most needed it.
            rows, total, exact = list_entity(
                _db, descriptor, _tenant_scope,
                skip=skip, limit=limit, id=id,
                filters={k: v for k, v in filters.items() if v is not None},
                sort_by=sort_by, sort_order=sort_order,
                after_id=after_id, include_total=include_total,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return _page(rows, total, exact, skip, limit)

    # The declared filters are spliced into the signature FastAPI reads, so each appears in the
    # OpenAPI schema by name. Without this they would arrive through `**filters`, which FastAPI
    # cannot document and would not validate.
    base = [p for p in inspect.signature(list_rows).parameters.values()
            if p.kind is not inspect.Parameter.VAR_KEYWORD]
    list_rows.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        base + _filter_parameters(descriptor))
    router.add_api_route(
        f'/{key}', list_rows, methods=['GET'], response_model=descriptor.page_schema,
        summary=f'List {key}',
    )

    def get_row(
        row_id: int,
        db: Session = Depends(get_db),
        _: str = view,
        scope: Optional[TenantScope] = scope_dependency,
    ):
        row = get_entity_row(db, descriptor, row_id, scope)
        if row is None:
            # 404 rather than 403: a 403 would confirm the id exists in some other tenant, which
            # lets a caller map the shape of data it cannot read.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{key} not found')
        return row

    router.add_api_route(
        f'/{key}/{{row_id}}', get_row, methods=['GET'], response_model=descriptor.read_schema,
        summary=f'Get one {key} row',
    )

    def create_row(
        payload: descriptor.create_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        username: str = edit,
        scope: Optional[TenantScope] = scope_dependency,
    ):
        try:
            # Through the descriptor's hooks, not around them: `before_create`/`after_create` are the
            # reuse surface the descriptor promises, and a generated route that called the query
            # core directly made every hook a declaration nothing ran.
            return create_entity_row(db, descriptor, payload, scope)
        except crud.TenantScopeError as exc:
            # 403 rather than 404: the caller named a tenant explicitly, so being told it may not
            # write there reveals nothing it did not already assert.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    if not descriptor.read_only:
        router.add_api_route(
            f'/{key}', create_row, methods=['POST'], response_model=descriptor.read_schema,
            status_code=status.HTTP_201_CREATED, summary=f'Create a {key} row',
        )

    def update_row(
        row_id: int,
        payload: descriptor.update_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        username: str = edit,
        scope: Optional[TenantScope] = scope_dependency,
    ):
        # `for_write`: a caller holding `:read_all_tenants` may SEE every tenant's rows and must
        # still get a 404 when it aims a PUT at one. The row-level policy would refuse the UPDATE
        # anyway, but a 404 is the honest answer rather than a write that silently affects nothing.
        row = get_entity_row(db, descriptor, row_id, scope, for_write=True)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{key} not found')
        return update_entity_row(db, descriptor, row, payload, scope)

    if not descriptor.read_only:
        router.add_api_route(
            f'/{key}/{{row_id}}', update_row, methods=['PUT'], response_model=descriptor.read_schema,
            summary=f'Update a {key} row',
        )

    def delete_row(
        row_id: int,
        db: Session = Depends(get_db),
        username: str = edit,
        scope: Optional[TenantScope] = scope_dependency,
    ):
        row = get_entity_row(db, descriptor, row_id, scope, for_write=True)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{key} not found')
        delete_entity_row(db, descriptor, row, scope)
        return None

    if not descriptor.read_only:
        router.add_api_route(
            f'/{key}/{{row_id}}', delete_row, methods=['DELETE'],
            status_code=status.HTTP_204_NO_CONTENT, summary=f'Delete a {key} row',
        )

    def describe(
        db: Session = Depends(get_db),
        _: str = view,
        scope: Optional[TenantScope] = scope_dependency,
    ):
        """What is queryable about THIS entity — behind this entity's own view permission.

        Generated per entity rather than served from one `/entities/{key}` route, for the same
        reason the CRUD routes are: the permission is the entity's, and a single parametric route
        could only check a permission it resolved at request time from a path parameter — or, as it
        first did here, check none at all. That mistake was not theoretical: a caller with no
        permission on the entity read its descriptor successfully, so a page probing for a refusal
        saw none and rendered an empty table instead of saying the caller may not look.
        """
        return entity_descriptor_payload(descriptor)

    router.add_api_route(
        f'/entities/{key}', describe, methods=['GET'],
        summary=f'What is queryable about {key}',
    )

    if descriptor.version_schema is not None and platform.audit is not None:
        _add_history_route(router, descriptor, filterable, platform, tenant_scoped)
    return router


def _add_history_route(router: APIRouter, descriptor, filterable: tuple, platform,
                       tenant_scoped: bool) -> None:
    """`GET /<key>/{id}/history` — only for an entity that declares a version schema.

    Mounted conditionally rather than always returning empty: an entity that is not versioned has
    no audit trail, and an endpoint that answers `[]` to that question is indistinguishable from
    one whose record is genuinely empty.

    `tenant_scoped` is `build_entity_router`'s, not recomputed: the same declaration decides
    whether THIS entity's history needs a tenant scope. No global versioned entity exists today —
    `list_item_history`'s WHERE clause still assumes a `tenant_id` column on the version table
    unconditionally, which is the part that would need revisiting first.
    """
    key = descriptor.key
    audit = platform.audit
    get_db = platform.get_db
    if tenant_scoped:
        history_scope_dependency = Depends(platform.require_tenant_scope())
    else:
        history_scope_dependency = Depends(lambda: None)

    def get_history(
        row_id: int,
        skip: int = 0,
        limit: int = Query(50, ge=1, le=crud.MAX_PAGE_SIZE),
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        actor: Optional[str] = None,
        operation_type: Optional[str] = None,
        timestamp: Optional[str] = None,
        # Cursor for the next (older) page: the oldest transaction_id already shown. Measured on a
        # 50,000-version record, the page at offset 49950 took 68 ms and the same page by cursor
        # 0.061 ms.
        before_transaction_id: Optional[int] = None,
        db: Session = Depends(get_db),
        _: str = Depends(platform.require_permission(
            f'{platform.module_slug}.{AUDIT_PERMISSION_RESOURCE}:view')),
        scope: Optional[TenantScope] = history_scope_dependency,
    ):
        row = get_entity_row(db, descriptor, row_id, scope)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'{key} not found')

        startup_at = audit.get_system_startup_at()
        try:
            version_table = version_class(descriptor.model).__table__.name
            # The table name comes from the ORM, never from the request: `list_item_history`
            # interpolates it into SQL.
            page_rows, total = crud.list_item_history(
                db, version_table=version_table, item_id=row_id, scope=scope,
                startup_at=startup_at, system_actor=audit.system_actor_username,
                # The version schema's own extra fields, not guessed: `tracked` (the synthetic
                # row, a few lines below) is already built from this same tuple, so one list
                # names what the version schema carries in both places history can produce a row.
                tracked_columns=filterable,
                skip=skip, limit=limit, sort_by=sort_by, sort_order=sort_order,
                actor=actor, operation_type=operation_type, timestamp=timestamp,
                before_transaction_id=before_transaction_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except SQLAlchemyError as exc:
            # Degrading to an empty history here rendered a synthetic "created" row: a record with
            # a real history became one that looked like it had never changed.
            db.rollback()
            logger.error('Audit trail: version rows unreadable for %s %s', key, row_id,
                         exc_info=True)
            raise audit.unavailable_error('version rows unreadable') from exc

        if total == 0:
            # A record whose versioning began after it was created has no version rows at all. The
            # synthetic row is built directly, and only on the first page, so paging past it
            # returns nothing rather than repeating it.
            tracked = {column: getattr(row, column) for column in filterable}
            synthetic = [] if skip > 0 else [audit.make_synthetic_creation_row(
                descriptor.version_schema, row, startup_at, **tracked)]
            return {
                'items': synthetic,
                'total': len(synthetic) if skip == 0 else 1,
                'page': (skip // limit) + 1 if limit > 0 else 1,
                'size': limit,
                'pages': 1,
            }

        items = [descriptor.version_schema(
            transaction_id=raw['transaction_id'],
            operation_type=int(raw['operation_type']),
            end_transaction_id=raw['end_transaction_id'],
            id=raw['id'],
            timestamp=audit.ensure_utc(raw['ts']),
            actor=raw['actor'],
            actor_id=None,
            **{column: raw[column] for column in filterable},
        ) for raw in page_rows]

        return {
            'items': items,
            'total': total,
            'page': (skip // limit) + 1 if limit > 0 else 1,
            'size': limit,
            'pages': (total + limit - 1) // limit if limit > 0 else 1,
        }

    router.add_api_route(
        f'/{key}/{{row_id}}/history', get_history, methods=['GET'],
        response_model=descriptor.version_page_schema,
        summary=f'Audit trail for one {key} row',
    )


def _key_parameters(descriptor) -> list[inspect.Parameter]:
    """One optional query parameter per key column, under the descriptor's OWN column names.

    `user_fk`, `profile_fk`, `tenant_fk` are the names a client already sends, so they are spliced
    into the handler's signature rather than read out of a generic bag: an OpenAPI schema that does
    not name them is a schema a caller cannot read. The descriptor refuses a key column named like
    one of `LIST_QUERY_PARAMETERS` at construction, so these cannot collide with the ones below.
    """
    return [
        inspect.Parameter(column, inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Optional[int])
        for column in descriptor.key_cols
    ]


def build_association_router(descriptor, platform) -> APIRouter:
    """The five endpoints for one association, closed over its descriptor and the module's platform.

    An association is not an entity: it has no id of its own in the API (the synthetic id is its
    address), no history of its own, and no `/entities` entry — its queryable names are the joined
    text, which the page declares. What it does have is its own permission, its own page envelope,
    and the descriptor's hooks, which is where a module's rules over its own link tables live.
    """
    from .associations import (AssociationError, create_association, delete_association, get_one,
                               list_page, update_association)

    key = descriptor.key
    router = APIRouter(prefix=f'/{key}', tags=[key])
    get_db = platform.get_db
    view = Depends(platform.require_permission(permission_for(platform, descriptor, 'view')))
    edit = Depends(platform.require_permission(permission_for(platform, descriptor, 'edit')))

    def _answer(exc: AssociationError):
        # The query side carries the status it means and raises no HTTP error of its own (it must
        # stay importable with no web stack); this is where it becomes one. A hook's own
        # `HTTPException` is not an `AssociationError` and passes through untouched.
        return HTTPException(status_code=exc.status_code, detail=exc.detail)

    def list_rows(
        *,
        skip: int = 0,
        limit: int = Query(100, ge=1, le=crud.MAX_PAGE_SIZE),
        id: Optional[str] = None,
        filters: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        # Underscored, like the entity list handler's: these are dependencies, not query parameters,
        # and the key columns share this signature under their own names.
        _db: Session = Depends(get_db),
        _: str = view,
        **keys: Any,
    ):
        try:
            return list_page(
                _db, descriptor, skip=skip, limit=limit, id=id,
                left_fk=keys.get(descriptor.left_col),
                right_fk=keys.get(descriptor.right_col),
                scope_fk=keys.get(descriptor.scope_col) if descriptor.scope_col else None,
                filters=filters, sort_by=sort_by, sort_order=sort_order,
            )
        except AssociationError as exc:
            raise _answer(exc)

    # The key columns are spliced into the signature FastAPI reads, so each appears in the OpenAPI
    # schema by name — the same mechanism the entity list endpoint uses for its filterable columns.
    base = [p for p in inspect.signature(list_rows).parameters.values()
            if p.kind is not inspect.Parameter.VAR_KEYWORD]
    list_rows.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        base + _key_parameters(descriptor))
    router.add_api_route(
        '', list_rows, methods=['GET'], response_model=descriptor.page_schema,
        summary=f'List {key}',
    )

    def get_row(
        association_id: str,
        db: Session = Depends(get_db),
        _: str = view,
    ):
        try:
            return get_one(db, descriptor, association_id)
        except AssociationError as exc:
            raise _answer(exc)

    router.add_api_route(
        '/{association_id}', get_row, methods=['GET'], response_model=descriptor.read_schema,
        summary=f'Get one {key} row',
    )

    def create_row(
        payload: descriptor.create_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        _: str = edit,
    ):
        try:
            return create_association(
                db, descriptor,
                getattr(payload, descriptor.left_col), getattr(payload, descriptor.right_col),
                getattr(payload, descriptor.scope_col) if descriptor.scope_col else None,
            )
        except AssociationError as exc:
            raise _answer(exc)

    router.add_api_route(
        '', create_row, methods=['POST'], response_model=descriptor.read_schema,
        status_code=status.HTTP_201_CREATED, summary=f'Create a {key} row',
    )

    def update_row(
        association_id: str,
        payload: descriptor.update_schema,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        _: str = edit,
    ):
        try:
            return update_association(
                db, descriptor, association_id,
                getattr(payload, descriptor.left_col), getattr(payload, descriptor.right_col),
                getattr(payload, descriptor.scope_col) if descriptor.scope_col else None,
            )
        except AssociationError as exc:
            raise _answer(exc)

    router.add_api_route(
        '/{association_id}', update_row, methods=['PUT'], response_model=descriptor.read_schema,
        summary=f'Update a {key} row',
    )

    def delete_row(
        association_id: str,
        db: Session = Depends(get_db),
        _: str = edit,
    ):
        try:
            delete_association(db, descriptor, association_id)
        except AssociationError as exc:
            raise _answer(exc)
        return None

    router.add_api_route(
        '/{association_id}', delete_row, methods=['DELETE'],
        status_code=status.HTTP_204_NO_CONTENT, summary=f'Delete a {key} row',
    )
    return router
