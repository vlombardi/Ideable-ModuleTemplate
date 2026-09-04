#!/usr/bin/env python3
"""The one implementation of the merged compose's generation.

The merged `deployment_root/docker-compose.yml` is **assembled from the module
compose files**, not re-derived from `docker compose config` output. That
distinction is the whole design:

`docker compose config` produces a normalised document — and normalising means
discarding every comment, sorting services alphabetically, and sorting the keys
*inside* each service alphabetically too. The merged file is what a devops
engineer reads on the deployed machine, and the comments in the module composes
are written for exactly that reader. Re-deriving the document threw away 44 of
the 100 comment lines the modules carry, and the survivors — only the banners
directly above a service — landed on the wrong services once the alphabetical
sort moved things around, so `# SYNC-MANAGED-END:` markers ended up above their
own `# SYNC-MANAGED-BEGIN:`.

Assembling from the sources instead gives, for free, what post-processing could
only approximate:

- every comment, in its authored place, including the ones inside service bodies;
- each comment block bound to the service it documents — the run above a service
  is its heading, a run touching the service's last line is its trailer — so a
  service and its markers travel together and stay paired under any ordering;
- services ordered by the dependency graph (providers first, `depends_on`
  respected), modules kept contiguous and each module's own grouping preserved,
  rather than alphabetically.

`docker compose config` still runs, but as a **validation gate on the assembled
file** rather than as its source, which is the stronger check anyway: it
validates the artefact that actually ships.

Two callers generate this file:

- `scripts/common/build_and_deploy.py`, at build time, and
- `scripts/runtime/config/create-merged-configuration.sh`, at the deploy site
  from the per-module composes already deployed there — including the run
  `redeploy.sh` performs immediately after the build-time one.

They used to carry a copy each of the generation logic. The copies drifted, and
the second caller then overwrote the first caller's correct output with its own
stale result: a migrations job whose only variables were a `DATABASE_URL` and a
defaulted `${LOG_LEVEL:-INFO}` — both values containing colons — lost its entire
environment block, so `alembic upgrade head` ran with no database to upgrade.
Hence one module, imported by both: a merge with two owners is a merge that
disagrees with itself.
"""
from __future__ import annotations

import heapq
import os
import posixpath
import re


def build_compose_clean_env(env):
    """Return the environment used while resolving the merged compose file.

    Module-local identity variables are intentionally stripped so a later-loaded
    module cannot leak its slug/name into the merged docker compose config.
    """
    scrub_prefixes = (
        "POSTGRES_", "APP_", "AUTHENTIK_", "VITE_", "BACKEND_", "FRONTEND_",
        "TEMPLATE_", "HOSTAPP_", "DATABASE_", "TIMESCALE", "NODE_", "CLIENT_",
        "TRAEFIK_", "TLS_", "LE_", "ACME_", "JWT_", "CORS_", "PUBLIC_",
        "INITIAL_", "EXTERNAL_", "MAIN_", "DATA_", "PROJECT_", "MODULE_",
    )
    return {
        k: v
        for k, v in env.items()
        if not any(k.startswith(prefix) for prefix in scrub_prefixes)
    }


def _read_env_keys(env_path):
    """Return the set of variable names defined in an .env file."""
    keys = set()
    if not os.path.exists(env_path):
        return keys
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.add(key)
    return keys


# ── Reading a compose file as text, with its comments ───────────────────────────
#
# Everything below works on lines, never on a parsed YAML tree: a tree cannot
# hold comments, and comments are the point.


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def _strip_blank_edges(lines: list) -> list:
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


SYNC_END_MARKER = "SYNC-MANAGED-END:"
SYNC_MARKER = "SYNC-MANAGED-"


def _split_comment_run(run: list, touches_previous: bool):
    """Split a run of comment/blank lines into (trailer, heading).

    A comment run sitting between two definitions can belong to either of them,
    and reading the whole run as the *next* definition's heading is what used to
    move every `SYNC-MANAGED-END` marker onto the following service.

    Two rules, in order:

    1. A `SYNC-MANAGED-END:` line closes a block by definition, so everything up
       to and including the last one is the trailer. This is decided explicitly
       rather than by layout because the module composes are inconsistent about
       it — host_app writes the marker directly under the service's last line,
       module_template leaves a blank line above it.
    2. Otherwise, a comment touching the previous definition's last line with no
       blank line between closes it; everything from the first blank line
       onwards introduces what comes next.
    """
    for index in range(len(run) - 1, -1, -1):
        if SYNC_END_MARKER in run[index]:
            return _strip_blank_edges(run[:index + 1]), _strip_blank_edges(run[index + 1:])
    if not touches_previous:
        return [], _strip_blank_edges(run)
    cut = 0
    while cut < len(run) and run[cut].strip().startswith("#"):
        cut += 1
    return _strip_blank_edges(run[:cut]), _strip_blank_edges(run[cut:])


def _without_sync_markers(lines: list) -> list:
    return _strip_blank_edges([ln for ln in lines if SYNC_MARKER not in ln])


def _split_entries(lines: list, indent: int) -> list:
    """Split the body of a top-level mapping into comment-aware entries.

    Returns ``[{"name", "heading", "body", "trailer"}]`` for every key at
    ``indent``. Each entry owns the comments that document it: those above it,
    and those closing it. Comments *inside* a body simply stay where they are.
    """
    entries = []
    pending: list = []
    prev_indent = None
    current = None

    for line in lines:
        if _is_blank_or_comment(line):
            pending.append(line)
            continue
        line_indent = _indent_of(line)
        stripped = line.strip()
        is_entry = (
            line_indent == indent
            and stripped.endswith(":")
            and not stripped.startswith("-")
        )
        if is_entry:
            trailer, heading = _split_comment_run(
                pending, prev_indent is not None and prev_indent > indent
            )
            if current is not None:
                current["trailer"] = trailer
                entries.append(current)
            elif trailer:
                # No previous entry to close: the run is all heading.
                heading = _strip_blank_edges(trailer + heading)
            current = {
                "name": stripped[:-1].strip(),
                "heading": heading,
                "body": [line],
                "trailer": [],
            }
        elif current is not None:
            current["body"].extend(pending)
            current["body"].append(line)
        pending = []
        prev_indent = line_indent

    if current is not None:
        trailer, _ = _split_comment_run(
            pending, prev_indent is not None and prev_indent > indent
        )
        current["trailer"] = trailer
        entries.append(current)
    return entries


def split_compose_document(text: str) -> dict:
    """Split a compose file into its top-level sections, preserving every line.

    Returns ``{key: {"heading": [...], "body": [...]}}`` in file order. A comment
    run between two sections is divided the same way as one between two services.
    """
    sections: dict = {}
    pending: list = []
    current_key = None
    prev_indent = None

    for line in text.splitlines(keepends=True):
        if _is_blank_or_comment(line):
            pending.append(line)
            continue
        line_indent = _indent_of(line)
        stripped = line.strip()
        if line_indent == 0 and stripped.endswith(":"):
            trailer, heading = _split_comment_run(
                pending, prev_indent is not None and prev_indent > 0
            )
            if current_key is not None:
                sections[current_key]["body"].extend(trailer)
            current_key = stripped[:-1].strip()
            sections.setdefault(current_key, {"heading": heading, "body": []})
        elif current_key is not None:
            sections[current_key]["body"].extend(pending)
            sections[current_key]["body"].append(line)
        pending = []
        prev_indent = line_indent

    if current_key is not None:
        trailer, _ = _split_comment_run(
            pending, prev_indent is not None and prev_indent > 0
        )
        sections[current_key]["body"].extend(trailer)
    return sections


# ── Per-service transformations ────────────────────────────────────────────────


def _strip_env_file(body: list) -> list:
    """Drop each service's `env_file:` block.

    The merged compose carries only what a service declares in `environment:`,
    and resolves `${VAR}` from the root `.env.config`/`.env.secrets`. Leaving the
    per-module `env_file:` entries in would re-import every module variable into
    every service — which is what the merge exists to prevent.
    """
    out = []
    skipping = False
    for line in body:
        stripped = line.strip()
        line_indent = _indent_of(line)
        if line_indent == 4 and stripped.startswith("env_file:"):
            skipping = True
            continue
        if skipping:
            if not stripped or line_indent > 4:
                continue
            skipping = False
        out.append(line)
    return out


def _rewrite_module_relative_paths(body: list, module_name: str) -> list:
    """Re-root a module's bind-mount paths on deployment_root.

    A module compose names its own files relative to itself (`./config/x`); the merged file is
    read from deployment_root, where the same file is `./modules/<module>/config/x`. Deployed
    module composes have already been re-rooted, so the rewrite skips anything already under
    `./modules/` and is safe to apply twice.

    Paths that climb out of the module directory are re-rooted too, and that case is not
    hypothetical: host_app mounts `../../modules:/modules:ro` so the Authentik bootstrap can read
    every module's `config/authorization.yaml` and build the authorization plan. Left alone, that
    string resolves two levels above deployment_root — a directory that does not exist, which
    Docker silently creates empty. The bootstrap then finds no module authorization files, the
    generated blueprint carries no module permissions, and users log in with a valid token that
    grants nothing: no claims, no menu, no pages. A mount that silently becomes an empty
    directory is worse than one that fails, so anything still escaping deployment_root after
    rewriting raises instead.
    """
    out = []
    for line in body:
        stripped = line.strip()
        for marker in ("- ", "source: "):
            if not stripped.startswith(marker):
                continue
            value = stripped[len(marker):]
            if not (value.startswith("./") or value.startswith("../")):
                continue
            if value.startswith("./modules/"):
                continue
            host_path, sep, rest = value.partition(":")
            # Where this path points once read from deployment_root instead of the module dir.
            rerooted = posixpath.normpath(posixpath.join("modules", module_name, host_path))
            if rerooted.startswith(".."):
                raise ValueError(
                    f"'{module_name}' mounts '{host_path}', which escapes deployment_root. "
                    f"Volume mounts must reference paths inside deployment_root."
                )
            line = line.replace(value, f"./{rerooted}{sep}{rest}", 1)
            break
        out.append(line)
    return out


def _declared_dependencies(body: list) -> set:
    """Service names this service's `depends_on:` names, in either form."""
    deps = set()
    in_depends_on = False
    for line in body[1:]:
        if _is_blank_or_comment(line):
            continue
        line_indent = _indent_of(line)
        stripped = line.strip()
        if line_indent <= 4:
            in_depends_on = line_indent == 4 and stripped == "depends_on:"
            continue
        if in_depends_on and line_indent == 6:
            if stripped.startswith("- "):
                deps.add(stripped[2:].strip())
            elif stripped.endswith(":"):
                deps.add(stripped[:-1].strip())
    return deps


# ── Ordering ───────────────────────────────────────────────────────────────────


def order_services_by_dependency(units: list, warn=None) -> list:
    """Order services so that every provider precedes its dependents.

    A topological walk of the `depends_on` graph, with ties broken by the
    service's position in its own module compose — so a module's services stay
    contiguous and in the grouping their author chose, and the order still reads
    as the startup order. (Compose itself has always ordered startup from
    `depends_on`; this makes the *file* say the same thing, instead of listing
    `traefik` before `database` because 't' follows 'd'.)
    """
    by_name = {u["name"]: u for u in units}
    unmet = {}
    dependents: dict = {}
    for unit in units:
        internal = {d for d in unit["deps"] if d in by_name}
        unmet[unit["name"]] = len(internal)
        for dep in internal:
            dependents.setdefault(dep, []).append(unit["name"])

    def priority(unit):
        return (unit["module_index"], unit["authored_index"], unit["name"])

    ready = [priority(u) for u in units if unmet[u["name"]] == 0]
    heapq.heapify(ready)
    ordered = []
    while ready:
        name = heapq.heappop(ready)[2]
        ordered.append(by_name[name])
        for dependent in sorted(dependents.get(name, [])):
            unmet[dependent] -= 1
            if unmet[dependent] == 0:
                heapq.heappush(ready, priority(by_name[dependent]))

    if len(ordered) != len(units):
        # A cycle: docker compose would reject it too, but the merged file must
        # still be written so the error is reported against a real artefact.
        placed = {u["name"] for u in ordered}
        stranded = [u for u in units if u["name"] not in placed]
        if warn:
            warn(
                "WARNING: circular depends_on among "
                + ", ".join(sorted(u["name"] for u in stranded))
                + " — those services keep their authored order."
            )
        ordered.extend(sorted(stranded, key=priority))
    return ordered


# ── Assembly ───────────────────────────────────────────────────────────────────


def _render(parts: list) -> str:
    return "".join(parts)


def _entry_text(entry: dict) -> str:
    body = list(entry["body"])
    while body and not body[-1].strip():
        body.pop()
    return _render(entry["heading"] + body + entry["trailer"])


def _module_scoped_values(compose_path, root_keys):
    """`{VAR: value}` for variables a module defines privately.

    Most module variables end up in the merged root `.env.config`/`.env.secrets`, so the merged
    compose can keep referencing them as `${VAR}`. A few are per-module *by design* — `MODULE_SLUG`
    and `MODULE_DOCKER_REGISTRY_PREFIX` have a different value in every module, so there is no
    single root value they could resolve to, and the merge deliberately does not export them.

    A `${MODULE_SLUG}` left in the merged file therefore resolves to the empty string, and every
    module's services collapse onto the same container name:

        services.template-database: container name "ideable..database" is already in use

    So these are substituted with their module's literal value while that module is being read —
    which is also what makes the merged file readable: `ideable.template.database`, not a
    reference that only means something next to the right .env file.
    """
    # MODULE_DOCKER_REGISTRY_PREFIX is deliberately NOT resolved here. It has its own
    # local/remote semantics in build_and_deploy._resolve_docker_registry_prefix: for a module
    # declared "local" the placeholder is *stripped* so the locally built image name is used,
    # and only a "remote" module keeps the registry path. Substituting the literal value here
    # would point a locally built stack at a registry image that may not exist or may be stale.
    values = {}
    module_dir = os.path.dirname(os.path.abspath(compose_path))
    for name in (".env.config", ".env.secrets"):
        path = os.path.join(module_dir, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if key and key not in root_keys and key != "MODULE_DOCKER_REGISTRY_PREFIX":
                    values[key] = value.strip()
    return values


def _module_env_all(compose_path):
    """Every variable a module's own .env files define, unfiltered."""
    values = {}
    module_dir = os.path.dirname(os.path.abspath(compose_path))
    for name in (".env.config", ".env.secrets"):
        path = os.path.join(module_dir, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def _resolve_module_scoped(text, values):
    """Replace `${VAR}` and `${VAR:-default}` for module-scoped VARs only."""
    if not values:
        return text
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-[^}]*)?\}")

    def _sub(match):
        key = match.group(1)
        if key in values:
            return values[key]
        return match.group(0)

    return pattern.sub(_sub, text)


def _module_mode(compose_path, module_name):
    """"local" or "remote" for a module, from `modules/enabled.md`.

    Defaults to "local": a module nobody declared remote is built here, and pointing a locally
    built stack at a registry image is the more damaging guess of the two.
    """
    modules_dir = os.path.dirname(os.path.dirname(os.path.abspath(compose_path)))
    enabled = os.path.join(modules_dir, "enabled.md")
    if not os.path.exists(enabled):
        return "local"
    with open(enabled, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or ":" not in line:
                continue
            name, _, mode = line.partition(":")
            if name.strip() == module_name:
                return mode.strip().lower() or "local"
    return "local"


def _resolve_registry_prefix(text, compose_path, module_name, module_env):
    """Apply the local/remote image-name rule to `${MODULE_DOCKER_REGISTRY_PREFIX}`.

    This mirrors build_and_deploy._resolve_docker_registry_prefix, and is duplicated rather than
    imported because compose_merge is copied to deployment_root and must stand alone.

    A "local" module is built here, so the placeholder is STRIPPED and the locally built image
    name is used. Only a "remote" module keeps the registry path. Left unresolved, the reference
    would expand to the empty string and yield an invalid image name like `/template.backend`;
    resolved unconditionally to the module's literal prefix, a locally built stack would silently
    run a stale registry image instead of the one just built.
    """
    prefix = ""
    if _module_mode(compose_path, module_name) == "remote":
        prefix = module_env.get("MODULE_DOCKER_REGISTRY_PREFIX", "").strip().rstrip("/")
    replacement = f"{prefix}/" if prefix else ""
    text = text.replace("${MODULE_DOCKER_REGISTRY_PREFIX}/", replacement)
    text = text.replace("${MODULE_DOCKER_REGISTRY_PREFIX}", replacement)
    return text


def collect_modules(compose_paths: list, root_keys=frozenset()) -> list:
    """Read each `(module_name, path)` into its split sections."""
    modules = []
    for module_name, path in compose_paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        module_env = _module_scoped_values(path, root_keys)
        text = _resolve_module_scoped(text, module_env)
        text = _resolve_registry_prefix(text, path, module_name, _module_env_all(path))
        modules.append((module_name, split_compose_document(text)))
    return modules


def assemble_merged_compose(compose_paths, project_slug=None, header=None, warn=None,
                            root_keys=frozenset()):
    """Build the merged compose text from the module compose files.

    ``compose_paths`` is ``[(module_name, path)]`` in module order (host_app
    first). Returns the file text.
    """
    modules = collect_modules(compose_paths, root_keys)

    units = []
    seen: dict = {}
    for module_index, (module_name, sections) in enumerate(modules):
        service_lines = sections.get("services", {}).get("body", [])
        for authored_index, entry in enumerate(_split_entries(service_lines, 2)):
            if entry["name"] in seen:
                raise ValueError(
                    f"service '{entry['name']}' is defined by both "
                    f"'{seen[entry['name']]}' and '{module_name}'"
                )
            seen[entry["name"]] = module_name
            body = _strip_env_file(entry["body"])
            body = _rewrite_module_relative_paths(body, module_name)
            units.append({
                "name": entry["name"],
                "heading": entry["heading"],
                "body": body,
                "trailer": entry["trailer"],
                "deps": _declared_dependencies(entry["body"]),
                "module": module_name,
                "module_index": module_index,
                "authored_index": authored_index,
            })

    ordered = order_services_by_dependency(units, warn=warn)

    def section_notes(section):
        """Each module's own commentary above a section, minus its sync markers.

        `SYNC-MANAGED-*` markers around a top-level `networks:`/`volumes:` key
        delimit that *module's* block for the sync script, which only ever reads
        per-module composes. In a file that unions every module's networks they
        would wrap other modules' entries too, so they are not carried over —
        every other comment is.
        """
        notes = []
        for _module_name, sections in modules:
            for line in sections.get(section, {}).get("heading", []):
                if SYNC_MARKER not in line:
                    notes.append(line)
        return _strip_blank_edges(notes)

    def render_section(key, entries, separator):
        if not entries:
            return
        notes = section_notes(key)
        if notes:
            out.extend(notes)
            out.append("\n")
        out.append(f"{key}:\n")
        out.append(separator.join(entries))
        out.append("\n")

    out = []
    if header:
        out.extend(header)
    if project_slug:
        out.append(f"name: {project_slug}\n\n")

    # Top-level networks/volumes: the union across modules, first declaration
    # wins. A module re-declaring a shared network (every module declares
    # `ideable_network`) adds nothing, so its block is simply not emitted.
    sections_rendered = {}
    for section in ("networks", "volumes"):
        emitted = []
        declared = set()
        for module_name, module_sections in modules:
            if section not in module_sections:
                continue
            for entry in _split_entries(module_sections[section]["body"], 2):
                if entry["name"] in declared:
                    continue
                declared.add(entry["name"])
                # Same reasoning as section_notes(): a per-module sync marker
                # cannot delimit anything meaningful inside a unioned section.
                entry["heading"] = _without_sync_markers(entry["heading"])
                entry["trailer"] = _without_sync_markers(entry["trailer"])
                emitted.append(_entry_text(entry))
        sections_rendered[section] = emitted

    render_section("networks", sections_rendered["networks"], "")
    render_section("services", [_entry_text(unit) for unit in ordered], "\n")
    render_section("volumes", sections_rendered["volumes"], "")
    return _render(out)


MERGED_HEADER = [
    "# AUTO-GENERATED — do not edit manually.\n",
    "# Edit the source docker-compose.yml in each module and re-run.\n",
    "#\n",
    "# Assembled from the module compose files, so the comments below are the ones\n",
    "# their authors wrote — including the SYNC-MANAGED markers, which delimit the\n",
    "# blocks the module-sync script maintains. Services are ordered by the\n",
    "# dependency graph (providers first), each module's services kept together.\n",
    "\n",
]


def write_merged_compose(
    compose_paths,
    deployment_root,
    project_slug=None,
    log=print,
    fail=None,
):
    """Assemble, validate and write ``<deployment_root>/docker-compose.yml``.

    The file is validated with `docker compose config` before it replaces the
    existing one, so a merge that would not parse never reaches the deploy site.
    """
    import subprocess
    import tempfile

    def _fail(message):
        if fail:
            fail(message)
        raise SystemExit(1)

    if not compose_paths:
        log("No compose files found — skipped merged docker-compose.yml generation")
        return None

    try:
        # Variables the merged root env defines can stay as ${VAR} references; the rest are
        # module-scoped and must be resolved per module before merging.
        root_keys = set()
        for name in (".env.config", ".env.secrets"):
            root_keys |= _read_env_keys(os.path.join(deployment_root, name))
        text = assemble_merged_compose(
            compose_paths, project_slug, MERGED_HEADER, warn=log, root_keys=root_keys
        )
    except ValueError as exc:
        _fail(f"ERROR: cannot merge module compose files: {exc}")

    target = os.path.join(deployment_root, "docker-compose.yml")
    handle, staged = tempfile.mkstemp(
        dir=deployment_root, prefix=".docker-compose.", suffix=".yml"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text)

        command = ["docker", "compose", "--project-directory", deployment_root]
        for name in (".env.config", ".env.secrets"):
            path = os.path.join(deployment_root, name)
            if os.path.exists(path):
                command.extend(["--env-file", path])
        if project_slug:
            command.extend(["--project-name", project_slug])
        command.extend(["-f", staged, "config", "-q"])

        result = subprocess.run(
            command,
            cwd=deployment_root,
            capture_output=True,
            text=True,
            env=build_compose_clean_env(os.environ),
        )
        if result.returncode != 0:
            log("ERROR: the merged docker-compose.yml is not a valid compose file")
            log("  " + " ".join(command))
            log(result.stderr.strip())
            _fail("ERROR: merged docker-compose.yml rejected by docker compose")

        os.replace(staged, target)
        staged = None
    finally:
        if staged and os.path.exists(staged):
            os.unlink(staged)

    modules = ", ".join(name for name, _ in compose_paths)
    log(f"- Created merged docker-compose.yml from modules: {modules}")
    return target
