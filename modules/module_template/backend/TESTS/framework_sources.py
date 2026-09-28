"""Where the framework's backend implementation is, for the tests that read it as text.

Several checks in this suite assert a property of the generic query core or of the generated
router by reading the source — that a query compiles without literal binds, that a cursor is a
seek, that no endpoint is declared without a permission. Those files are not this module's: they
are `ideable_api` (`reusable.api/README.md`), shared by every backend and reached here through the
tracked `SOURCES/.ideable-api` symlink.

One place resolves them, because the alternative is what happened the last time this moved: each
test file carried its own path and the refactor failed them all at COLLECTION, one by one.

A caveat worth knowing before adding to that group of checks: a test that greps source passes on a
guard that has been commented out and fails on a rename that changed nothing. Prefer exercising the
behaviour where the behaviour is reachable; read the text only for properties that have no runtime
face.
"""
from pathlib import Path

#: `reusable.api/ideable_api/`, via the symlink each backend's SOURCES carries.
FRAMEWORK = Path(__file__).resolve().parents[1] / "SOURCES" / ".ideable-api" / "ideable_api"

#: The generic query core — `app.crud` re-exports it under the name this backend calls it by.
QUERY = FRAMEWORK / "query.py"

#: The generated endpoints.
ROUTER = FRAMEWORK / "router.py"

#: The registry and the descriptor contract.
ENTITIES = FRAMEWORK / "entities.py"

#: The association registry and the query side that serves a module's link tables.
ASSOCIATIONS = FRAMEWORK / "associations.py"


def read(path: Path) -> str:
    assert path.exists(), (
        f"{path} does not exist: the shared framework package is reached through "
        f"SOURCES/.ideable-api, and either that symlink is missing or the file moved within "
        f"reusable.api/ — see reusable.api/README.md"
    )
    return path.read_text(encoding="utf-8")
