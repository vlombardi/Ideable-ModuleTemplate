#!/usr/bin/env python3
"""
Synchronise agent skill directories from the canonical .agents/skills source.

Two synchronisation strategies are used:

1. **Symlink** (.claude/skills, .kiro/skills)
   These directories are replaced with symlinks to ../.agents/skills so
   that editing a skill in one place immediately takes effect for all
   compatible AI development environments.

2. **Copy** (.devin/skills)
   Devin expects real files, not symlinks.  This script copies every skill
   directory from .agents/skills/ into .devin/skills/, removing any stale
   skill directories that no longer exist in the canonical source.

3. **Workflow generation** (.devin/workflows/)
   Three Ideable-specific skills have content-identical counterparts as
   Devin workflow files.  This script generates them from the canonical
   skill SKILL.md files, stripping the ``name:`` frontmatter field so
   that only ``description:`` remains (the Devin workflow format).

Run this script after a fresh clone, after adding/removing skills, or
to verify the current state with --validate.
"""

import os
import shutil
import sys
from pathlib import Path


# Relative symlink target from each tool directory to the canonical source.
# e.g. .claude/skills -> ../.agents/skills
SYMLINK_TARGET = Path("..") / ".agents" / "skills"

# Tool directories that must be symlinks.
SYMLINK_TOOL_DIRS = [".claude", ".kiro"]

# Tool directory that must be a real-directory copy (Devin requires real files).
COPY_TOOL_DIR = ".devin"

# Skills whose SKILL.md should also be exported as Devin workflow files.
# Mapping: skill directory name -> workflow filename.
# The script also checks for underscore variants of the skill dir name.
WORKFLOW_MAP = {
    "build-and-deploy": "Build&Deploy.md",
    "implement-specs": "ImplementSpecs.md",
    "test-and-fix": "Tests&Fix.md",
}


def _resolve_skill_dir(canonical: Path, skill_name: str) -> Path | None:
    """Resolve a skill directory name, trying hyphen and underscore variants."""
    for candidate in (skill_name, skill_name.replace("-", "_")):
        path = canonical / candidate
        if path.is_dir():
            return path
    return None


def get_project_root() -> Path:
    """Walk up from CWD (or script location) until .agents/skills is found."""
    candidates = [Path.cwd(), Path(__file__).parent.resolve()]
    for start in candidates:
        for path in [start, *start.parents]:
            if (path / ".agents" / "skills").exists():
                return path
    raise RuntimeError(
        "Could not find project root: no .agents/skills directory found "
        "in the current directory or any of its parents."
    )


# ---------------------------------------------------------------------------
# Symlink logic (for .claude, .kiro)
# ---------------------------------------------------------------------------

def check_or_fix_symlink(
    tool_dir: Path,
    skills_name: str,
    dry_run: bool,
) -> tuple[str, str]:
    """
    Ensure <tool_dir>/skills is a symlink pointing to SYMLINK_TARGET.

    Returns (status, message) where status is one of:
      'ok'       — already correct, nothing done
      'created'  — symlink created (or would be in dry-run)
      'fixed'    — wrong symlink target corrected
      'replaced' — real directory replaced with symlink
      'error'    — could not fix (e.g. unexpected file type)
    """
    target_path = tool_dir / skills_name

    # --- Case 1: already a correct symlink ---
    if target_path.is_symlink():
        current_target = Path(os.readlink(target_path))
        if current_target == SYMLINK_TARGET:
            return ("ok", f"{target_path}: OK (symlink → {SYMLINK_TARGET})")
        # Wrong target — re-point it
        action = f"re-point symlink: {current_target} → {SYMLINK_TARGET}"
        if not dry_run:
            target_path.unlink()
            target_path.symlink_to(SYMLINK_TARGET)
        return ("fixed", f"{target_path}: FIXED ({action})")

    # --- Case 2: does not exist yet ---
    if not target_path.exists():
        action = f"create symlink → {SYMLINK_TARGET}"
        if not dry_run:
            tool_dir.mkdir(parents=True, exist_ok=True)
            target_path.symlink_to(SYMLINK_TARGET)
        return ("created", f"{target_path}: CREATED ({action})")

    # --- Case 3: real directory (e.g. after manual copy or old script run) ---
    if target_path.is_dir():
        action = f"remove directory and create symlink → {SYMLINK_TARGET}"
        if not dry_run:
            shutil.rmtree(target_path)
            target_path.symlink_to(SYMLINK_TARGET)
        return ("replaced", f"{target_path}: REPLACED real directory with symlink ({action})")

    # --- Case 4: regular file or other unexpected type ---
    return (
        "error",
        f"{target_path}: ERROR — unexpected filesystem object (not a dir/symlink). "
        "Remove it manually and re-run.",
    )


# ---------------------------------------------------------------------------
# Copy logic (for .devin/skills)
# ---------------------------------------------------------------------------

def _list_canonical_skills(canonical: Path) -> list[str]:
    """Return sorted list of skill directory names in .agents/skills/."""
    return sorted(
        entry.name
        for entry in canonical.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    )


def _dirs_are_identical(a: Path, b: Path) -> bool:
    """Shallow check: same file names and same file contents (by read)."""
    a_files = {p.name: p for p in a.rglob("*") if p.is_file()}
    b_files = {p.name: p for p in b.rglob("*") if p.is_file()}
    if set(a_files) != set(b_files):
        return False
    for name in a_files:
        try:
            if a_files[name].read_bytes() != b_files[name].read_bytes():
                return False
        except OSError:
            return False
    return True


def sync_copy_dir(
    project_root: Path,
    dry_run: bool,
) -> tuple[str, str]:
    """
    Sync .devin/skills/ from .agents/skills/ as a real-directory copy.

    Returns (status, message).
    """
    canonical = project_root / ".agents" / "skills"
    dest = project_root / COPY_TOOL_DIR / "skills"

    canonical_skills = _list_canonical_skills(canonical)
    actions: list[str] = []
    changed = False

    # Ensure dest exists
    if not dest.exists():
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)
        actions.append(f"created {dest}/")
        changed = True
    elif not dest.is_dir():
        return ("error", f"{dest}: ERROR — not a directory. Remove it manually and re-run.")

    # Remove stale skill dirs in dest that are not in canonical
    if dest.is_dir():
        dest_skills = _list_canonical_skills(dest)
        for name in dest_skills:
            if name not in canonical_skills:
                if not dry_run:
                    shutil.rmtree(dest / name)
                actions.append(f"removed stale skill: {name}/")
                changed = True

    # Copy/update each canonical skill
    for name in canonical_skills:
        src_skill = canonical / name
        dst_skill = dest / name
        if dst_skill.exists() and _dirs_are_identical(src_skill, dst_skill):
            continue
        if not dry_run:
            if dst_skill.exists():
                shutil.rmtree(dst_skill)
            shutil.copytree(src_skill, dst_skill)
        actions.append(f"{'updated' if dst_skill.exists() else 'copied'} skill: {name}/")
        changed = True

    if not changed:
        return ("ok", f"{dest}: OK ({len(canonical_skills)} skills in sync)")
    return ("synced", f"{dest}: {'SYNCED' if not dry_run else '[DRY RUN] WOULD SYNC'} ({'; '.join(actions)})")


# ---------------------------------------------------------------------------
# Workflow generation logic (for .devin/workflows/)
# ---------------------------------------------------------------------------

def _skill_to_workflow_content(skill_md: Path) -> str:
    """Read a SKILL.md file and return its content with the ``name:`` frontmatter line removed."""
    text = skill_md.read_text()
    # Strip the `name:` line from the YAML frontmatter, keeping everything else.
    lines = text.splitlines(keepends=True)
    in_frontmatter = False
    result: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            result.append(line)
            continue
        if in_frontmatter and stripped.startswith("name:"):
            continue  # skip the name: line
        result.append(line)
    return "".join(result)


def sync_workflows(
    project_root: Path,
    dry_run: bool,
) -> tuple[str, str]:
    """
    Generate .devin/workflows/ files from the canonical skill SKILL.md files.

    Returns (status, message).
    """
    canonical = project_root / ".agents" / "skills"
    workflows_dir = project_root / COPY_TOOL_DIR / "workflows"

    actions: list[str] = []
    changed = False

    if not workflows_dir.exists():
        if not dry_run:
            workflows_dir.mkdir(parents=True, exist_ok=True)
        actions.append(f"created {workflows_dir}/")
        changed = True

    for skill_name, workflow_filename in WORKFLOW_MAP.items():
        skill_dir = _resolve_skill_dir(canonical, skill_name)
        if skill_dir is None:
            actions.append(f"SKIP {workflow_filename} (skill {skill_name} not found)")
            continue

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            actions.append(f"SKIP {workflow_filename} (skill {skill_dir} not found)")
            continue

        workflow_path = workflows_dir / workflow_filename
        new_content = _skill_to_workflow_content(skill_md)

        if workflow_path.exists() and workflow_path.read_text() == new_content:
            continue

        if not dry_run:
            workflow_path.write_text(new_content)
        actions.append(f"{'updated' if workflow_path.exists() else 'generated'} workflow: {workflow_filename}")
        changed = True

    if not changed:
        return ("ok", f"{workflows_dir}: OK ({len(WORKFLOW_MAP)} workflows in sync)")
    return ("synced", f"{workflows_dir}: {'SYNCED' if not dry_run else '[DRY RUN] WOULD SYNC'} ({'; '.join(actions)})")


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def validate(project_root: Path) -> int:
    """Check parity without modifying anything. Returns 0 if all OK, 1 otherwise."""
    canonical = project_root / ".agents" / "skills"
    errors = 0

    # Check symlinks
    for tool_dir_name in SYMLINK_TOOL_DIRS:
        target = project_root / tool_dir_name / "skills"
        if not target.is_symlink():
            print(f"  ERROR: {target} is not a symlink")
            errors += 1
        else:
            current = Path(os.readlink(target))
            if current != SYMLINK_TARGET:
                print(f"  ERROR: {target} -> {current} (expected {SYMLINK_TARGET})")
                errors += 1
            else:
                print(f"  OK: {target} -> {SYMLINK_TARGET}")

    # Check .devin/skills copy
    dest = project_root / COPY_TOOL_DIR / "skills"
    if not dest.exists():
        print(f"  ERROR: {dest} does not exist")
        errors += 1
    else:
        canonical_skills = _list_canonical_skills(canonical)
        dest_skills = _list_canonical_skills(dest)
        missing = set(canonical_skills) - set(dest_skills)
        stale = set(dest_skills) - set(canonical_skills)
        for name in sorted(missing):
            print(f"  ERROR: .devin/skills/ missing skill: {name}/")
            errors += 1
        for name in sorted(stale):
            print(f"  ERROR: .devin/skills/ stale skill: {name}/")
            errors += 1
        for name in sorted(set(canonical_skills) & set(dest_skills)):
            if _dirs_are_identical(canonical / name, dest / name):
                print(f"  OK: .devin/skills/{name}/")
            else:
                print(f"  ERROR: .devin/skills/{name}/ content differs from canonical")
                errors += 1

    # Check .devin/workflows
    workflows_dir = project_root / COPY_TOOL_DIR / "workflows"
    for skill_name, workflow_filename in WORKFLOW_MAP.items():
        skill_dir = _resolve_skill_dir(canonical, skill_name)
        if skill_dir is None:
            print(f"  SKIP: {workflow_filename} (skill {skill_name} not found)")
            continue
        skill_md = skill_dir / "SKILL.md"
        workflow_path = workflows_dir / workflow_filename
        if not skill_md.exists():
            print(f"  SKIP: {workflow_filename} (skill {skill_dir} not found)")
            continue
        if not workflow_path.exists():
            print(f"  ERROR: {workflow_path} missing")
            errors += 1
            continue
        expected = _skill_to_workflow_content(skill_md)
        if workflow_path.read_text() == expected:
            print(f"  OK: {workflow_path}")
        else:
            print(f"  ERROR: {workflow_path} content differs from canonical skill")
            errors += 1

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Synchronise agent skill directories from .agents/skills.\n"
            "  - .claude/skills, .kiro/skills: symlinks\n"
            "  - .devin/skills: real-directory copy\n"
            "  - .devin/workflows: generated from Ideable-specific skills"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making any changes.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Check parity without modifying anything. Exits 0 if all OK, 1 otherwise.",
    )
    parser.add_argument(
        "--target",
        choices=["claude", "windsurf", "kiro", "devin", "all"],
        default="all",
        help="Which tool directory to check/fix (default: all).",
    )
    args = parser.parse_args()

    try:
        project_root = get_project_root()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.validate:
        print(f"Project root : {project_root}")
        print(f"Canonical src: {project_root / '.agents' / 'skills'}")
        print("Mode         : VALIDATE")
        print()
        errors = validate(project_root)
        print()
        print("=" * 60)
        if errors:
            print(f"VALIDATION FAILED — {errors} error(s) found")
        else:
            print("VALIDATION PASSED — all skills in sync")
        print("=" * 60)
        return 1 if errors else 0

    print(f"Project root : {project_root}")
    print(f"Canonical src: {project_root / '.agents' / 'skills'}")
    if args.dry_run:
        print("Mode         : DRY RUN (no changes will be made)")
    print()

    counts: dict[str, int] = {}

    # --- Symlink targets ---
    symlink_tools = (
        SYMLINK_TOOL_DIRS
        if args.target == "all" or args.target == "devin"
        else [f".{args.target}"]
    )
    # If --target is devin, skip symlink tools
    if args.target == "devin":
        symlink_tools = []

    for tool_dir_name in symlink_tools:
        tool_dir = project_root / tool_dir_name
        status, message = check_or_fix_symlink(tool_dir, "skills", args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run and status != "ok" else ""
        print(f"  {prefix}{message}")
        counts[status] = counts.get(status, 0) + 1

    # --- Copy target (.devin/skills) ---
    if args.target == "all" or args.target == "devin":
        status, message = sync_copy_dir(project_root, args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run and status != "ok" else ""
        print(f"  {prefix}{message}")
        counts[status] = counts.get(status, 0) + 1

        # --- Workflow generation (.devin/workflows) ---
        status, message = sync_workflows(project_root, args.dry_run)
        prefix = "[DRY RUN] " if args.dry_run and status != "ok" else ""
        print(f"  {prefix}{message}")
        counts[status] = counts.get(status, 0) + 1

    print()
    print("=" * 60)
    if args.dry_run:
        print("DRY RUN COMPLETE — no changes were made")
    else:
        print("DONE")
    for label, count in sorted(counts.items()):
        if count:
            print(f"  {label}: {count}")
    print("=" * 60)

    return 1 if counts.get("error", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
