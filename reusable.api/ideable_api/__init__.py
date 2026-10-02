"""`ideable_api` — the Ideable framework's backend implementation, shared by every module.

The frontend counterpart is `@ideable/ui` (`reusable.ui/`), and the arrangement is deliberately the
same one: the framework's implementation lives ONCE, at the repository top level, and every
module's backend — host_app included — consumes it from there. A module adopts it or writes its
own; what a module never does is carry its own copy.

    tenancy       `TenantScope` — whose data a request may touch
    query         the generic list/read/write core, model-parameterised
    entities      `EntityDescriptor`, the per-module registry, and the descriptor-driven face of query
    associations  `AssociationDescriptor`, the same for a module's link tables, and their query side
    router        the generated endpoints for a declared entity or association
    platform      what the framework needs FROM the module hosting it

WHAT IS PER MODULE AND WHAT IS SHARED. The registry is per module: each backend declares its own
entities, and since a backend is one module's process, its registry is this package's process-global
one. The code that gives a descriptor meaning is shared, and is what lives here.

NO MODULE IMPORTS. Nothing here may import a module's `app` package. Where the framework needs
something only a module knows — a session, a permission check, a tenant scope, an audit trail — the
module passes it in as a `Platform` (`platform.py`).

HOW IT REACHES A BACKEND. A relative symlink in the backend's `SOURCES/`, exactly as
`SOURCES/.ideable-ui` works on the frontend, plus a named `ideable_api` build context so the image
build can copy it in — a symlink pointing outside the build context does not resolve for Docker.
Both are set up by the backend's `SPECS/build.sh`; see `README.md`.
"""
