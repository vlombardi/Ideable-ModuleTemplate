#!/usr/bin/env python3
"""Fail a deploy whose images are not the build it just made.

Every image built here is `<slug>.<submodule>:latest`, so the NAME cannot say which build a
container runs. The LABELS can: `build_and_deploy.py` stamps `org.opencontainers.image.revision`
(the commit), `org.opencontainers.image.created` and `tech.ideable.dirty` on every image it builds.
This script reads the revision back and compares it with `HEAD`.

Why the comparison exists. A failed `docker build` leaves the PREVIOUS image under `latest`, and a
build.sh that forgot the labels produces an image with no revision at all — in both cases compose
starts something, every container comes up healthy, and nothing says it is not the code that was
just written. Before labels, the same class of failure was caught by comparing two tags written
into `deployment_root/.env.config` by two different writers; that needed the keys to be preserved
across both writers, and the one time they were not, a wrong deploy looked completely healthy.
The label needs no bookkeeping: it is part of the image.

Two entry points, one check:

- `check_image(image, expected_revision)` — one image, called by `build_and_deploy.py` right after
  each build, so a stale image fails the deploy before anything else is built on top of it.
- `verify(repo_root)` / the CLI — every locally built image the deployed compose names, called by
  `redeploy.sh` after the merge, so the whole deployment is checked once more as a set.

Consumed images (host_app in a remote project, pulled from a registry) carry the publisher's
revision, not this checkout's, so only images of modules enabled `local` are compared.

Exit codes: 0 every local image is the build from HEAD (or there is none, and it says so), 1 not.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))

LABEL_REVISION = "org.opencontainers.image.revision"
LABEL_DIRTY = "tech.ideable.dirty"
LOCAL_IMAGE_TAG = "latest"


def head_revision(repo_root=_PROJECT_ROOT):
    """The short commit of the checkout, or None when this is not one."""
    try:
        out = subprocess.run(["git", "-C", repo_root, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def docker_labels(image):
    """The labels of a local image as a dict, or None when the image does not exist locally."""
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .Config.Labels}}", image],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout.strip() or "null") or {}
    except json.JSONDecodeError:
        return {}


def check_image(image, expected_revision, labels_of=docker_labels):
    """(ok, message) for one image. `labels_of` is injectable so the contract test needs no docker."""
    labels = labels_of(image)
    if labels is None:
        return False, f"ERROR: {image} does not exist locally after the build."
    revision = (labels.get(LABEL_REVISION) or "").strip()
    dirty = (labels.get(LABEL_DIRTY) or "").strip() == "true"
    if not revision:
        return False, (
            f"ERROR: {image} carries no {LABEL_REVISION} label.\n"
            f"  It was not built by this deploy (or by a build.sh that stamps the identity), so which\n"
            f"  code it runs cannot be known. Rebuild it through ./redeploy.sh."
        )
    if revision != expected_revision:
        return False, (
            f"ERROR: {image} is a stale build.\n"
            f"    image revision : {revision}\n"
            f"    checkout HEAD  : {expected_revision}\n"
            f"  The build did not produce a new image, so `latest` still names the previous one and\n"
            f"  the stack would run code that is not what was just written. Look for a failed\n"
            f"  `docker build` above, or a build.sh that tagged a different name."
        )
    suffix = " (built from a dirty tree)" if dirty else ""
    return True, f"{image} is the build from {revision}{suffix}"


def _module_modes(repo_root):
    """{module name: "local"|"remote"} from modules/enabled.md."""
    enabled = os.path.join(repo_root, "modules", "enabled.md")
    modes = {}
    if not os.path.isfile(enabled):
        return modes
    with open(enabled, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            name, _, mode = line.partition(":")
            mode = mode.strip().lower()
            if mode in ("local", "remote"):
                modes[name.strip()] = mode
    return modes


def _local_module_slugs(repo_root):
    """Slugs of the modules enabled `local` — the ones whose images are built, not pulled."""
    enabled = os.path.join(repo_root, "modules", "enabled.md")
    slugs = set()
    if not os.path.isfile(enabled):
        return slugs
    with open(enabled, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            name, _, mode = line.partition(":")
            if mode.strip().lower() != "local":
                continue
            meta = os.path.join(repo_root, "modules", name.strip(), "module.json")
            try:
                with open(meta, encoding="utf-8") as fh:
                    slug = (json.load(fh).get("slug") or "").strip()
            except (OSError, json.JSONDecodeError):
                slug = ""
            slugs.add(slug or name.strip().lower().replace("_", ""))
    return slugs


def local_module_images(repo_root=_PROJECT_ROOT):
    """The `image:` references in deployment_root/docker-compose.yml that this checkout built.

    A locally built module's reference has no registry (the deploy strips the prefix) and ends in
    the local tag: `hostapp.backend:latest`. `postgres:16-alpine` has no registry either, which is
    why the module slug is required to match — third-party images are never this checkout's build.
    """
    compose = os.path.join(repo_root, "deployment_root", "docker-compose.yml")
    if not os.path.isfile(compose):
        return []
    slugs = _local_module_slugs(repo_root)
    if not slugs:
        return []
    pattern = re.compile(
        r"^\s*image:\s*[\"']?((?:" + "|".join(re.escape(s) for s in sorted(slugs)) + r")\.[A-Za-z0-9_.-]+:"
        + re.escape(LOCAL_IMAGE_TAG) + r")[\"']?\s*$",
        re.MULTILINE,
    )
    seen, out = set(), []
    with open(compose, encoding="utf-8") as handle:
        for match in pattern.finditer(handle.read()):
            if match.group(1) not in seen:
                seen.add(match.group(1))
                out.append(match.group(1))
    return out


def docker_image_id(reference):
    """The local image id `reference` names, or '' when nothing local answers to it."""
    out = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", reference],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def consumed_hostapp_refs(repo_root=_PROJECT_ROOT):
    """[(ref, digest)] for a host_app this project CONSUMES, or [] when it builds one.

    The pair comes from framework.env + framework.lock.json through the one resolver. When the two
    disagree the resolver raises, and that is reported as a failure rather than skipped: a project
    that cannot say which release it runs must not deploy.
    """
    if _module_modes(repo_root).get("host_app") != "remote":
        return []
    # The resolver is in `scripts/runtime/` — it has to be at a deployed site, and one copy of a
    # reader is the whole point. Dev imports runtime; runtime imports nothing from here.
    sys.path.insert(0, str(Path(_HERE).parents[1] / "runtime"))
    import framework_version  # noqa: PLC0415 — optional dependency of this path only

    refs = framework_version.hostapp_image_refs(Path(repo_root))
    return [(r.ref, r.digest) for r in sorted(refs.values(), key=lambda r: r.name)]


def check_consumed_image(ref, digest, ids_of=docker_image_id):
    """(ok, message) for one consumed image: the local tag must BE the digest the lock names."""
    repo = ref.rsplit(":", 1)[0]
    tagged = ids_of(ref)
    wanted = ids_of(f"{repo}@{digest}")
    if not tagged:
        return False, (
            f"ERROR: {ref} is not present locally.\n"
            f"  It is consumed, not built here. Pull it: deployment_root/scripts/pull-hostapp-images.sh"
        )
    if not wanted:
        return False, (
            f"ERROR: {ref} is present locally but {digest[:19]}… — the digest the lock names — is not.\n"
            f"  The image was pulled under this name from a different publish, or built by hand.\n"
            f"  Pull the release the lock names: deployment_root/scripts/pull-hostapp-images.sh"
        )
    if tagged != wanted:
        return False, (
            f"ERROR: {ref} does not point at the digest the framework lock names.\n"
            f"    lock digest : {digest}\n"
            f"  The tag was moved, locally or in the registry, so the stack would run a build this\n"
            f"  project never agreed to. Re-sync and pull:\n"
            f"    scripts/dev/module/sync-template-updates.sh && deployment_root/scripts/pull-hostapp-images.sh"
        )
    return True, f"{ref} is the digest the lock names ({digest[:19]}…)"


def verify(repo_root=_PROJECT_ROOT, labels_of=docker_labels):
    """(ok, message) for every locally built image the deployed compose names."""
    expected = head_revision(repo_root)
    if not expected:
        return False, "ERROR: not a git checkout, so there is no revision to compare the images with."
    images = local_module_images(repo_root)
    if not images:
        # Nothing built here (a project consuming every module) — say so rather than report a
        # verification that compared nothing.
        return True, ("NOTE: deployment_root/docker-compose.yml names no locally built image, so there "
                      "is no build identity to verify here.")
    lines, ok_all = [], True
    for image in images:
        ok, message = check_image(image, expected, labels_of)
        ok_all = ok_all and ok
        lines.append(message)
    head = ("Build identity verified: every local image is the build from " + expected
            if ok_all else "Build identity FAILED:")
    return ok_all, head + "\n  " + "\n  ".join(lines)


def verify_all(repo_root=_PROJECT_ROOT, labels_of=docker_labels, ids_of=docker_image_id):
    """Everything the stack is about to run: what this checkout built, and what it consumes."""
    ok, message = verify(repo_root, labels_of)
    try:
        consumed = consumed_hostapp_refs(repo_root)
    except Exception as exc:  # noqa: BLE001 — the resolver's own message is the diagnosis
        return False, message + f"\nConsumed images FAILED:\n  {exc}"
    if not consumed:
        return ok, message
    lines, consumed_ok = [], True
    for ref, digest in consumed:
        one_ok, one_message = check_consumed_image(ref, digest, ids_of)
        consumed_ok = consumed_ok and one_ok
        lines.append(one_message)
    head = ("Consumed images verified: every one is the digest the framework lock names"
            if consumed_ok else "Consumed images FAILED:")
    return ok and consumed_ok, message + "\n" + head + "\n  " + "\n  ".join(lines)


def main(argv):
    repo_root = argv[1] if len(argv) > 1 else _PROJECT_ROOT
    ok, message = verify_all(repo_root)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
