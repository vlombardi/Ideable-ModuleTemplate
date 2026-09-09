#!/usr/bin/env python3
"""One version names the framework, and this is the only code that reads it.

Two files at the repository root, one reader:

- `framework.env` is the CHOICE. Exactly one line, `IDEABLE_FRAMEWORK_VERSION=<latest|X.Y.Z>`,
  edited by a person and tracked by the project. `latest` is a channel the project subscribes to;
  `X.Y.Z` pins a published release. There is no shell override and no flag: the file is the only
  source, and a one-line edit shows in `git diff`, which a shell variable never does.
- `framework.lock.json` is the FACTS. Written by the maintainer's publish, force-synced to every
  project, never hand-edited: the template repository, the dev tools image and its digest, the
  host_app registry and one digest per image — everything the version name resolved to at publish
  time.

  IT RECORDS NO TEMPLATE COMMIT, BECAUSE IT CANNOT. The publish copies this very file into the
  template repository and pushes it, so a `template.commit` would have to name the commit that
  contains the field naming it. A release is identified by its TAG on both sides — the publish
  creates it, `adopt_framework.sh` fetches it — and a tag is a name that can be written before the
  commit it points at exists. A lock still carrying the retired key validates: only the top-level
  key set is exact.

Every other reference to a framework version is DERIVED from these two through the functions below.
Shell callers go through the command-line entry point rather than parsing either file themselves —
a second parser is how two readers stop agreeing.

    python3 scripts/runtime/framework_version.py version
    python3 scripts/runtime/framework_version.py devtools-image-ref     # <image>:<version>
    python3 scripts/runtime/framework_version.py devtools-repo          # <image>, ungated
    python3 scripts/runtime/framework_version.py devtools-digest        # sha256:…
    python3 scripts/runtime/framework_version.py hostapp-image-refs     # <name> <ref> <digest> per line
    python3 scripts/runtime/framework_version.py deployed-hostapp-image-refs   # same, at a site
    python3 scripts/runtime/framework_version.py template-ref           # <repo> <ref>
    python3 scripts/runtime/framework_version.py check                  # both files valid and agreeing

`--root PATH` reads another tree's files, which is how the tests stage a project.

WHY THIS MODULE IS IN `runtime/` AND NOT BESIDE THE DEV TOOLING THAT ALSO IMPORTS IT. `runtime/` is
the deployed `scripts/` folder — copied whole, so membership is the folder rather than a list in
Python. A deployed site has to name the release it runs, so the one reader of the lock has to be in
the bundle; and there is exactly one copy of it, imported by the dev-side deploy from here, for the
same reason `compose_merge.py` has exactly one: two copies of a reader are how two answers appear.
Dev may import runtime; runtime never names a dev path, because no dev path exists at a site.

A DEPLOYED SITE INHERITS ITS RELEASE, IT DOES NOT CHOOSE IT. The deploy copies this module and
`framework.lock.json` next to the runtime scripts — but deliberately **not** `framework.env`. There
is no reason for a deployment to change what the module maintainer decided at coding time, and a
choice file sitting at a site is precisely the thing that could. So a site reads its release from
the lock that was deployed with it (`deployed_release` below), while a checkout — which does hold
the choice — still has the two compared. Before this, the site-side puller looked for
`framework.env`, found none, and walked up out of the deployment root into whatever checkout
happened to be above it: a deployed site reported the maintainer's release while holding none of
the files that name it.

WHY THE LOCK IS COMPARED WITH THE CHOICE. On `latest` the lock pins the digests of the last publish
the project synced, so a redeploy without a sync runs exactly what the last sync brought. When the
one line is edited to a pinned version, the lock still describes the previous one until the next
sync fetches the tagged template — and tagging that older digest with the new version name locally
would be a lie. So an image reference is only ever derived from a lock that was published for the
version the project asks for; a mismatch is reported with the command that resolves it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: True when this file is the checkout copy — the one under `scripts/runtime/`, from which the
#: project root really is `parents[2]`. The deploy copies this module into `deployment_root/scripts/`
#: with the rest of the folder, and from *there* `parents[2]` points ABOVE the deployment root:
#: defaulting to it would resolve a parent checkout's release and call it the site's. `_root()`
#: refuses to guess in that copy, so the defect can only reappear as a loud error. Pinned by
#: `test_a_deployed_site_resolves_its_own_release.py`.
_IS_CHECKOUT_COPY = Path(__file__).resolve().parent.name == "runtime"

ENV_FILE = "framework.env"
LOCK_FILE = "framework.lock.json"
VERSION_KEY = "IDEABLE_FRAMEWORK_VERSION"

#: `latest`, or three dot-separated numbers. Not `v1.2.0`: the `v` belongs to the git tag, which is
#: derived (`template_ref`), and a version written two ways is two versions.
_VERSION = re.compile(r"^(latest|\d+\.\d+\.\d+)$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCK_KEYS = {"version", "published_at", "template", "devtools", "host_app"}


class FrameworkVersionError(SystemExit):
    """Raised for every way the two files can be wrong. Exit status 1, message on stderr."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(1)


@dataclass(frozen=True)
class ImageRef:
    name: str
    ref: str
    digest: str


@dataclass(frozen=True)
class TemplateRef:
    repo: str
    ref: str


def is_pinned(version: str) -> bool:
    return version != "latest"


def _root(root: Path | None) -> Path:
    """The tree to read, refusing to guess from a copy that cannot know where it is."""
    if root is not None:
        return root
    if not _IS_CHECKOUT_COPY:
        raise FrameworkVersionError(
            f"{Path(__file__).name} was copied next to the runtime scripts, and a copy there cannot "
            f"work out which tree it belongs to: relative to it the project root would be ABOVE the "
            f"deployment root, so guessing resolves a parent checkout's release and calls it this "
            f"site's. Pass the deployment root explicitly (`--root <deployment root>`)."
        )
    return REPO_ROOT


# ── The choice: framework.env ─────────────────────────────────────────────────────────────────


def _strip_comment(line: str) -> str:
    """Drop a `#` comment. A `#` starts one at the beginning of a word only."""
    if line.lstrip().startswith("#"):
        return ""
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0]


def version(root: Path | None = None) -> str:
    """The one framework version this project asks for."""
    root = _root(root)
    if VERSION_KEY in os.environ:
        raise FrameworkVersionError(
            f"{VERSION_KEY} is set in the shell environment. {ENV_FILE} is the only source of the "
            f"framework version — there is no shell override, because an edit to the file shows in "
            f"`git diff` and a variable does not. Unset it and edit the one line in {ENV_FILE}."
        )
    path = root / ENV_FILE
    if not path.is_file():
        raise FrameworkVersionError(
            f"{ENV_FILE} is missing at {root}. It holds the one line "
            f"`{VERSION_KEY}=latest` (or `X.Y.Z`) that names the framework version this project runs."
        )
    keys: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if "=" not in line:
            raise FrameworkVersionError(
                f"{ENV_FILE}:{number}: `{raw.strip()}` is not `KEY=VALUE`. The file holds exactly one "
                f"line, `{VERSION_KEY}=<latest|X.Y.Z>`."
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if key in keys:
            raise FrameworkVersionError(f"{ENV_FILE}:{number}: `{key}` is set twice.")
        keys[key] = value.strip("\"'")
    extra = sorted(k for k in keys if k != VERSION_KEY)
    if extra:
        raise FrameworkVersionError(
            f"{ENV_FILE} sets {', '.join(extra)}, and it holds exactly one key: {VERSION_KEY}. "
            f"Every other fact about the framework version is derived from {LOCK_FILE}."
        )
    if VERSION_KEY not in keys:
        raise FrameworkVersionError(
            f"{ENV_FILE} does not set {VERSION_KEY}. The file holds exactly that one line, "
            f"`{VERSION_KEY}=latest` or `{VERSION_KEY}=X.Y.Z`."
        )
    value = keys[VERSION_KEY]
    if not _VERSION.match(value):
        hint = " Write it without the leading `v`; the git tag is derived." if value.startswith("v") else ""
        raise FrameworkVersionError(
            f"{ENV_FILE}: {VERSION_KEY}={value!r} is neither `latest` nor `X.Y.Z`.{hint}"
        )
    return value


# ── The facts: framework.lock.json ────────────────────────────────────────────────────────────


def _require(mapping: object, key: str, where: str) -> object:
    if not isinstance(mapping, dict) or key not in mapping:
        raise FrameworkVersionError(
            f"{LOCK_FILE}: {where} has no `{key}`. The lock is generated by the framework publish and "
            f"never edited by hand — regenerate it rather than patching it."
        )
    return mapping[key]


def _require_digest(value: object, where: str) -> str:
    if not isinstance(value, str) or not _DIGEST.match(value):
        raise FrameworkVersionError(
            f"{LOCK_FILE}: {where} is {value!r}, not a `sha256:<64 hex>` digest. A lock carrying "
            f"anything but a registry digest was not written by the publish."
        )
    return value


def _require_text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrameworkVersionError(f"{LOCK_FILE}: {where} is empty.")
    return value


def validate_lock(lock: object) -> dict:
    """Return `lock` when it has exactly the schema the publish writes; raise otherwise."""
    if not isinstance(lock, dict):
        raise FrameworkVersionError(f"{LOCK_FILE}: the document is not a JSON object.")
    unknown = sorted(set(lock) - _LOCK_KEYS)
    missing = sorted(_LOCK_KEYS - set(lock))
    if unknown or missing:
        raise FrameworkVersionError(
            f"{LOCK_FILE}: keys must be exactly {sorted(_LOCK_KEYS)}; "
            f"missing {missing}, unknown {unknown}."
        )
    lock_version = _require_text(lock["version"], "`version`")
    if not _VERSION.match(lock_version):
        raise FrameworkVersionError(f"{LOCK_FILE}: `version` {lock_version!r} is neither `latest` nor `X.Y.Z`.")
    _require_text(lock["published_at"], "`published_at`")
    template = lock["template"]
    _require_text(_require(template, "repo", "`template`"), "`template.repo`")
    devtools = lock["devtools"]
    _require_text(_require(devtools, "image", "`devtools`"), "`devtools.image`")
    _require_digest(_require(devtools, "digest", "`devtools`"), "`devtools.digest`")
    host_app = lock["host_app"]
    _require_text(_require(host_app, "registry", "`host_app`"), "`host_app.registry`")
    images = _require(host_app, "images", "`host_app`")
    if not isinstance(images, dict) or not images:
        raise FrameworkVersionError(f"{LOCK_FILE}: `host_app.images` must map at least one image name to a digest.")
    for name, digest in images.items():
        _require_digest(digest, f"`host_app.images[{name!r}]`")
    return lock


def read_lock(root: Path | None = None) -> dict:
    root = _root(root)
    path = root / LOCK_FILE
    if not path.is_file():
        raise FrameworkVersionError(
            f"{LOCK_FILE} is missing at {root}. It is written by the framework publish. A module's\n"
            f"checkout gets it from `sync-template-updates.sh`; a deployed site gets it from the\n"
            f"deploy, which places it at the deployment root — so at a site this means the bundle\n"
            f"is incomplete, and redeploying is what fixes it."
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrameworkVersionError(f"{LOCK_FILE} is not valid JSON ({exc}). Regenerate it; do not edit it.") from exc
    return validate_lock(document)


def _lock_for(root: Path) -> tuple[str, dict]:
    """The lock, only when it was published for the version the project asks for."""
    wanted = version(root)
    lock = read_lock(root)
    if lock["version"] != wanted:
        raise FrameworkVersionError(
            f"{ENV_FILE} says {wanted} but {LOCK_FILE} was published for {lock['version']}. Image "
            f"references are derived only from a lock that matches, because naming a {lock['version']} "
            f"digest `{wanted}` locally would be a lie. In a module project run "
            f"`sync-template-updates.sh`; in the Ideable repository run the framework publish."
        )
    return wanted, lock


# ── Derived references ────────────────────────────────────────────────────────────────────────


def devtools_image_ref(root: Path | None = None) -> str:
    """`<image>:<version>` — the tag the toolbox runs under locally; its bytes come from the lock."""
    wanted, lock = _lock_for(_root(root))
    return f"{lock['devtools']['image']}:{wanted}"


def devtools_repo(root: Path | None = None) -> str:
    """The toolbox's image REPOSITORY, with no tag — and not gated on the lock matching the version.

    Same exemption, and the same reason, as `template_ref` below: the publish is the step that
    brings a matching lock, so it must be able to ask where to push while the two still disagree.
    A repository name contains no version, so answering it during that window states nothing that
    could be wrong — whereas `devtools_image_ref` appends the version and is gated, because naming
    a `latest` digest `1.6.3` locally would be a lie.

    Before this existed, the publish resolved the repository through the gated reference and died
    at its second step on every release: naming a new version is exactly what puts `framework.env`
    ahead of the lock, so a first pinned release could never get past it.
    """
    lock = read_lock(_root(root))
    return lock["devtools"]["image"]


def devtools_digest(root: Path | None = None) -> str:
    _, lock = _lock_for(_root(root))
    return lock["devtools"]["digest"]


def _refs_from(wanted: str, lock: dict) -> dict[str, ImageRef]:
    registry = lock["host_app"]["registry"].rstrip("/")
    return {
        name: ImageRef(name=name, ref=f"{registry}/{name}:{wanted}", digest=digest)
        for name, digest in lock["host_app"]["images"].items()
    }


def hostapp_image_refs(root: Path | None = None) -> dict[str, ImageRef]:
    """One `<registry>/<name>:<version>` per host_app image, each with the digest that must back it."""
    return _refs_from(*_lock_for(_root(root)))


# ── What a deployed site inherits ─────────────────────────────────────────────────────────────


def deployed_release(root: Path) -> tuple[str, dict]:
    """The release the tree at `root` runs — chosen if it holds the choice, inherited if it does not.

    The presence of `framework.env` is not a fallback signal, it is the DEFINITION of the two
    layouts, and both are fully specified:

    - A **checkout** holds the choice, so the choice governs and the lock must have been published
      for it — `_lock_for`'s comparison, unchanged. Pulling the lock's digests while the one line
      asks for another release is exactly the lie that comparison exists to refuse.
    - A **deployed site** holds no choice, by design: the deploy copies the lock and never
      `framework.env`, because a deployment has no business re-deciding what the module maintainer
      decided at coding time. The deployed lock is therefore the whole statement of the release, and
      its own `version` names it.

    `root` is required — there is no default. A site's copy of this module cannot infer its own
    tree, and inferring it wrongly is the defect this function was written for.
    """
    if (root / ENV_FILE).is_file():
        return _lock_for(root)
    lock = read_lock(root)
    return lock["version"], lock


def deployed_hostapp_image_refs(root: Path) -> dict[str, ImageRef]:
    """`hostapp_image_refs` for a tree that may be a deployed site rather than a checkout."""
    return _refs_from(*deployed_release(root))


def hostapp_consumed_ref(root: Path | None = None) -> tuple[str, str]:
    """`(registry, version)` for the host_app release this project consumes.

    Both come from the lock, so a project running host_app as `remote` names the release the
    framework published rather than anything derived from its own checkout. The registry is the
    lock's, not `MODULE_DOCKER_REGISTRY_PREFIX` from host_app's `.env.config`: a remote project does
    not own host_app's images and must not be able to point them somewhere else by editing an env
    file it also uses for its own module.
    """
    wanted, lock = _lock_for(_root(root))
    return lock["host_app"]["registry"].rstrip("/"), wanted


def template_ref(root: Path | None = None) -> TemplateRef:
    """Where sync fetches the framework files: `main` on `latest`, the version itself when pinned.

    THE TAG IS THE VERSION, WITH NOTHING ADDED. `1.6.3` is fetched from `1.6.3`, not from `v1.6.3`:
    the maintainer names a release once, on the publish command line, and that string is the tag the
    publish writes and the tag a project fetches. A prefix invented on one side is a second naming
    rule that the other side has to know about, and the repositories this framework already
    published (`1.5.0`, `0.1`) never carried one.

    Not gated on the lock matching the version: sync is the step that brings a matching lock, so it
    must be able to ask where to fetch from while the two still disagree.
    """
    root = _root(root)
    wanted = version(root)
    lock = read_lock(root)
    ref = wanted if is_pinned(wanted) else "main"
    return TemplateRef(repo=lock["template"]["repo"], ref=ref)


# ── The writer ────────────────────────────────────────────────────────────────────────────────


def build_lock(
    *,
    version: str,
    published_at: str,
    template_repo: str,
    devtools_image: str,
    devtools_digest: str,
    registry: str,
    images: dict[str, str],
) -> dict:
    """Assemble a lock from published digests, refusing anything that is not one."""
    lock = {
        "version": version,
        "published_at": published_at,
        "template": {"repo": template_repo},
        "devtools": {"image": devtools_image, "digest": devtools_digest},
        "host_app": {"registry": registry.rstrip("/"), "images": dict(sorted(images.items()))},
    }
    return validate_lock(lock)


def write_lock(lock: dict, root: Path | None = None) -> Path:
    """Write a validated lock to `<root>/framework.lock.json`, stably formatted for review diffs."""
    validate_lock(lock)
    path = _root(root) / LOCK_FILE
    path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return path


# ── Command line ──────────────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="framework_version.py",
        description="The one reader of framework.env and framework.lock.json.",
    )
    parser.add_argument("command", choices=[
        "version", "devtools-image-ref", "devtools-repo", "devtools-digest", "hostapp-image-refs",
        "deployed-hostapp-image-refs", "template-ref", "check",
    ])
    parser.add_argument("--root", type=Path, default=None, help="project root (default: this repository)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        # Through `_root`, not `REPO_ROOT`: the copy beside the runtime scripts must be told which
        # tree to read rather than guessing a parent checkout's.
        root = args.root.resolve() if args.root else _root(None)
        if args.command == "version":
            print(version(root))
        elif args.command == "devtools-image-ref":
            print(devtools_image_ref(root))
        elif args.command == "devtools-digest":
            print(devtools_digest(root))
        elif args.command == "hostapp-image-refs":
            for image in hostapp_image_refs(root).values():
                print(f"{image.name} {image.ref} {image.digest}")
        elif args.command == "deployed-hostapp-image-refs":
            for image in deployed_hostapp_image_refs(root).values():
                print(f"{image.name} {image.ref} {image.digest}")
        elif args.command == "devtools-repo":
            print(devtools_repo(root))
        elif args.command == "template-ref":
            template = template_ref(root)
            print(f"{template.repo} {template.ref}")
        elif args.command == "check":
            wanted, lock = _lock_for(root)
            print(f"framework {wanted}: {ENV_FILE} and {LOCK_FILE} agree (published {lock['published_at']})")
    except FrameworkVersionError as exc:
        print(f"[framework-version] {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
