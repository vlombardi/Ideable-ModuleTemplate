"""The contract that keeps a service replicable.

Each assertion here corresponds to something that actually stopped the stack from scaling, and every
one of them is the kind of regression a reviewer waves through:

- a `container_name` on a replicable service caps it at ONE instance, because a container name is
  unique and the second replica collides on it. This is not a warning — Compose starts one replica and
  errors on the rest.
- a FIXED published port does the same ("port is already allocated"), and the obvious fix of a port
  *range* has its own trap: with a range and a single replica, Compose bound the LAST port and left the
  documented one dead, so `localhost:8001` answered nothing while the stack looked healthy. Hence one
  variable holding the whole port spec, defaulting to the exact fixed port.
- `traefik.*` labels describe routing that nothing performs: only the FILE provider is configured.
- `/var/run/docker.sock` was mounted and never read, which is root-equivalent access for nothing.

Static on purpose: this must fail in CI, where there is no Docker daemon to scale.

**Everything below is DISCOVERED, never named.** This file travels to every project generated from
`Ideable-ModuleTemplate`, where the module's directory carries the module's own name instead of
`module_template`, `modules/host_app/` holds only `module.json` and `config/` (host_app arrives as
pre-built images), and the maintainer's `docs/` is not synced at all. Naming `module_template`,
`template-backend`, `TEMPLATE_*` or host_app's sources made **17 of these tests fail in a remote
module project** the first time the CI gate ran there — reporting the framework's own assumptions as
the module's fault. The remote-safe test work.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

MODULE_DIR = Path(__file__).resolve().parents[1]        # modules/<THIS MODULE>
REPO_ROOT = MODULE_DIR.parents[1]                       # the project root
HOSTAPP_DIR = REPO_ROOT / "modules" / "host_app"


def _module_json(module_dir: Path) -> dict:
    """A module's identity, from the one file that travels with it and cannot be shadowed.

    `$MODULE_SLUG` is ambiguous by construction — every module's `.env.config` defines it, the merged
    `deployment_root` file carries host_app's value, and the runner exports it per module — which is
    why `backend/TESTS/conftest.py` already reads `module.json` instead. Same reason here.
    """
    return json.loads((module_dir / "module.json").read_text(encoding="utf-8"))


MODULE_SLUG = _module_json(MODULE_DIR)["slug"]
ENV_PREFIX = MODULE_SLUG.upper()

MODULE_COMPOSE = MODULE_DIR / "docker-compose.yml"
HOSTAPP = HOSTAPP_DIR / "docker-compose.yml"
HOSTAPP_DYNAMIC = HOSTAPP_DIR / "traefik" / "SOURCES" / "dynamic.yml.template"
ROLLING_DEPLOY = REPO_ROOT / "scripts" / "runtime" / "config" / "rolling-deploy.sh"
RUNBOOK = REPO_ROOT / "docs" / "RUNBOOK.md"

# (compose file, service, replicas var, publish var)
REPLICABLE = [
    (MODULE_COMPOSE, f"{MODULE_SLUG}-backend",
     f"{ENV_PREFIX}_BACKEND_REPLICAS", f"{ENV_PREFIX}_BACKEND_PUBLISH"),
    (MODULE_COMPOSE, f"{MODULE_SLUG}-frontend",
     f"{ENV_PREFIX}_FRONTEND_REPLICAS", f"{ENV_PREFIX}_FRONTEND_PUBLISH"),
    (HOSTAPP, "backend", "BACKEND_REPLICAS", "BACKEND_PUBLISH"),
    (HOSTAPP, "frontend", "FRONTEND_REPLICAS", "FRONTEND_PUBLISH"),
]

_COMPOSE_IDS = [f"{path.parent.name}:{service}" for path, service, _, _ in REPLICABLE]


def _require(path: Path, what: str) -> None:
    """Skip — with a reason that NAMES what is absent — when this is a remote module project.

    `rules/testing-guidelines.md`: never write a bare skip. The runner classifies reasons, and a
    reason that says *which* maintainer-only artifact is missing is the difference between "not
    applicable here" and "the runner failed to configure it".
    """
    if not path.exists():
        pytest.skip(
            f"{what} is absent ({path.relative_to(REPO_ROOT)}): this is a remote module project. "
            f"host_app ships there as pre-built images (modules/host_app/ holds only module.json "
            f"and config/) and the maintainer's docs/ is not synced, so this assertion belongs to "
            f"the Ideable main repository."
        )


def _service_block(path: Path, service: str) -> str:
    """The raw YAML text of one service, so `${VAR}` placeholders survive (yaml.safe_load keeps them
    as strings, but reading the text keeps the assertions honest about the default too)."""
    _require(path, f"{path.parent.name}'s compose file")
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(service)}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert match, f"service {service} not found in {path.name}"
    return match.group(0)


@pytest.mark.parametrize("path,service,replicas_var,publish_var", REPLICABLE, ids=_COMPOSE_IDS)
def test_replicable_services_have_no_container_name(path, service, replicas_var, publish_var):
    block = _service_block(path, service)
    assert "container_name:" not in block, (
        f"{service} declares a container_name, which caps it at one replica"
    )


@pytest.mark.parametrize("path,service,replicas_var,publish_var", REPLICABLE, ids=_COMPOSE_IDS)
def test_replica_count_is_parameterised_and_defaults_to_one(path, service, replicas_var, publish_var):
    block = _service_block(path, service)
    assert f"replicas: ${{{replicas_var}:-1}}" in block, (
        f"{service} does not take its replica count from {replicas_var}, defaulting to 1"
    )


@pytest.mark.parametrize("path,service,replicas_var,publish_var", REPLICABLE, ids=_COMPOSE_IDS)
def test_published_port_is_one_switchable_spec(path, service, replicas_var, publish_var):
    """One variable for the whole spec: a guaranteed port by default, a range when scaling."""
    block = _service_block(path, service)
    assert f"${{{publish_var}:-" in block, (
        f"{service} does not take its published port from {publish_var}"
    )
    # The DEFAULT must be a single fixed port, not a range: a range does not guarantee the documented
    # port, and every test and dev URL depends on it.
    default = re.search(rf"\$\{{{publish_var}:-([^}}]+)\}}", block).group(1)
    assert "-" not in default.split(":")[0], (
        f"{publish_var} defaults to the range {default!r}; with a range Compose may bind any port in "
        f"it and leave the documented one dead"
    )


@pytest.mark.parametrize("path", [HOSTAPP, MODULE_COMPOSE], ids=lambda p: p.parent.name)
def test_no_dead_traefik_labels(path):
    _require(path, f"{path.parent.name}'s compose file")
    content = path.read_text(encoding="utf-8")
    assert "traefik.http.routers" not in content, (
        "traefik.* routing labels are never read — only the file provider is configured"
    )


def test_traefik_does_not_mount_the_docker_socket():
    """Usage, not mention: the compose comment explains WHY the socket is absent, and a bare substring
    search reads that explanation as a violation — the same trap the migration tests document."""
    _require(HOSTAPP, "host_app's compose file")
    mounts = [
        line.strip() for line in HOSTAPP.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- ") and "/var/run/docker.sock" in line
    ]
    assert not mounts, (
        f"the docker socket is mounted again ({mounts}): no configured provider reads it, and read "
        f"access to it is root-equivalent on the host"
    )


def test_traefik_reaches_services_by_dns_name_not_by_container():
    """This is what makes replicas work with no Traefik change: Docker resolves the service name to
    every replica's address.

    The service names and ports come from each module's own `module.json`, so this keeps checking the
    right pair after a module is renamed.
    """
    _require(HOSTAPP_DYNAMIC, "host_app's Traefik dynamic configuration")
    dynamic = HOSTAPP_DYNAMIC.read_text(encoding="utf-8")
    targets = [
        ("backend", _module_json(HOSTAPP_DIR)["backendPort"]),
        (f"{MODULE_SLUG}-backend", _module_json(MODULE_DIR)["backendPort"]),
    ]
    for service, port in targets:
        assert f"http://{service}:{port}" in dynamic, (
            f"Traefik must address {service} by its compose service name to load-balance replicas"
        )


class TestRollingDeploy:
    """`scripts/runtime/` is synced to every remote project, so these run everywhere."""

    def test_the_script_exists_and_is_executable(self):
        assert ROLLING_DEPLOY.is_file(), "no rolling-deploy script"
        assert ROLLING_DEPLOY.stat().st_mode & 0o111, "rolling-deploy.sh is not executable"

    def test_it_never_recreates_the_whole_service(self):
        """`up -d <service>` without --no-recreate replaces every replica at once, which is the
        outage this script exists to avoid."""
        script = ROLLING_DEPLOY.read_text(encoding="utf-8")
        assert "--no-recreate" in script

    def test_it_waits_for_health_before_continuing(self):
        script = ROLLING_DEPLOY.read_text(encoding="utf-8")
        assert "wait_healthy" in script
        assert "State.Health.Status" in script, (
            "health must come from Docker's own healthcheck (the /ready probe), not a second weaker "
            "definition invented in the script"
        )

    def test_it_aborts_rather_than_continuing_past_a_bad_replica(self):
        script = ROLLING_DEPLOY.read_text(encoding="utf-8")
        assert "ABORTING the roll" in script, (
            "a roll that carries on past an unhealthy replica converts a bad image into an outage"
        )

    def test_it_says_so_when_there_is_only_one_replica(self):
        script = ROLLING_DEPLOY.read_text(encoding="utf-8")
        assert "ONE replica" in script

    def test_it_is_portable_to_bash_3(self):
        """macOS ships bash 3.2. `mapfile` is bash 4+, and a deploy script that only runs on the
        maintainer's Linux box is not a deploy script."""
        # Usage, not mention: the script's own comment explains why mapfile is avoided.
        script = ROLLING_DEPLOY.read_text(encoding="utf-8")
        uses = [
            line.strip() for line in script.splitlines()
            if "mapfile" in line and not line.strip().startswith("#")
        ]
        assert not uses, f"bash 4+ builtin in use: {uses}"


@pytest.mark.parametrize("path", [HOSTAPP, MODULE_COMPOSE], ids=lambda p: p.parent.name)
def test_compose_files_still_parse(path):
    """A YAML error here fails the deploy, not this test — unless this test catches it first."""
    _require(path, f"{path.parent.name}'s compose file")
    with path.open(encoding="utf-8") as handle:
        assert yaml.safe_load(handle), f"{path.name} did not parse"
