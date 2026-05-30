#!/usr/bin/env python3
"""
Script to replace symlinks in .claude/skills, .windsurf/skills, and .kiro/skills
with actual content from .agents/skills.

This script:
1. Removes symlinks from .claude/skills, .windsurf/skills, and .kiro/skills
2. Copies actual content from .agents/skills to these directories
3. Handles naming mismatches (e.g., authentik-traefik-guard -> authentik-traefik-security)
"""

import os
import shutil
import sys
from pathlib import Path

# Mapping of source directory names to target directory names
# Keys: source directory name in .agents/skills
# Values: target directory name in .claude/skills or .windsurf/skills
# NOTE: By default, source names are preserved. Add mappings here only if explicit renaming is needed.
NAME_MAPPING = {
    # Example: "old-name": "new-name",
}


def get_project_root() -> Path:
    """Get the project root directory."""
    # Script is in the project root or can be run from there
    cwd = Path.cwd()
    
    # Check if we're in the project root by looking for .agents/skills
    if (cwd / ".agents" / "skills").exists():
        return cwd
    
    # If script is in a subdirectory, go up
    script_dir = Path(__file__).parent.resolve()
    if (script_dir / ".agents" / "skills").exists():
        return script_dir
    
    # Try to find by looking for the directory
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".agents" / "skills").exists():
            return parent
    
    raise RuntimeError("Could not find project root with .agents/skills directory")


def remove_symlinks(skills_dir: Path, dry_run: bool = False) -> list[str]:
    """Remove all symlinks from a skills directory."""
    removed = []
    
    if not skills_dir.exists():
        print(f"Directory does not exist: {skills_dir}")
        return removed
    
    for item in skills_dir.iterdir():
        if item.is_symlink():
            if dry_run:
                print(f"[DRY RUN] Would remove symlink: {item.name}")
            else:
                item.unlink()
                print(f"Removed symlink: {item.name}")
            removed.append(item.name)
        elif item.is_file() and not item.is_symlink():
            # Skip regular files (like .DS_Store)
            continue
        elif item.is_dir() and not item.is_symlink():
            # Remove existing directories that might be old copies
            if dry_run:
                print(f"[DRY RUN] Would remove directory: {item.name}")
            else:
                shutil.rmtree(item)
                print(f"Removed directory: {item.name}")
            removed.append(item.name)
    
    return removed


def copy_skills(source_dir: Path, target_dir: Path, dry_run: bool = False) -> list[str]:
    """Copy skills from source to target directory."""
    copied = []
    
    if not source_dir.exists():
        raise RuntimeError(f"Source directory does not exist: {source_dir}")
    
    # Ensure target directory exists
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    
    for source_item in source_dir.iterdir():
        # Skip hidden files like .DS_Store
        if source_item.name.startswith("."):
            continue
        
        # Skip symlinks (including self-referential ones)
        if source_item.is_symlink():
            print(f"Skipping symlink: {source_item.name}")
            continue
        
        if not source_item.is_dir():
            continue
        
        # Determine target name (use mapping if exists)
        target_name = NAME_MAPPING.get(source_item.name, source_item.name)
        target_path = target_dir / target_name
        
        if dry_run:
            print(f"[DRY RUN] Would copy: {source_item.name} -> {target_name}")
        else:
            # Remove existing target if it exists
            if target_path.exists():
                if target_path.is_symlink():
                    target_path.unlink()
                else:
                    shutil.rmtree(target_path)
            
            # Copy directory, ignoring symlinks
            shutil.copytree(
                source_item, 
                target_path,
                ignore=lambda src, names: [n for n in names if (Path(src) / n).is_symlink()]
            )
            print(f"Copied: {source_item.name} -> {target_name}")
        
        copied.append(target_name)
    
    return copied


def update_skills_directory(target_dir: Path, source_dir: Path, dry_run: bool = False):
    """Update a skills directory by removing symlinks and copying actual content."""
    print(f"\n{'='*60}")
    print(f"Updating: {target_dir}")
    print(f"Source: {source_dir}")
    print(f"{'='*60}")
    
    # Remove symlinks and existing directories
    removed = remove_symlinks(target_dir, dry_run)
    print(f"Removed {len(removed)} items")
    
    # Copy actual content
    copied = copy_skills(source_dir, target_dir, dry_run)
    print(f"Copied {len(copied)} skills")
    
    return removed, copied


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Replace symlinks in .claude/skills, .windsurf/skills, and .kiro/skills with actual content from .agents/skills"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--target",
        choices=["claude", "windsurf", "kiro", "all"],
        default="all",
        help="Which directory to update (default: all)"
    )
    
    args = parser.parse_args()
    
    try:
        project_root = get_project_root()
        print(f"Project root: {project_root}")
        
        source_dir = project_root / ".agents" / "skills"
        
        targets = []
        if args.target in ("claude", "all"):
            targets.append(project_root / ".claude" / "skills")
        if args.target in ("windsurf", "all"):
            targets.append(project_root / ".windsurf" / "skills")
        if args.target in ("kiro", "all"):
            targets.append(project_root / ".kiro" / "skills")
        
        total_removed = 0
        total_copied = 0
        
        for target_dir in targets:
            removed, copied = update_skills_directory(target_dir, source_dir, args.dry_run)
            total_removed += len(removed)
            total_copied += len(copied)
        
        print(f"\n{'='*60}")
        if args.dry_run:
            print("DRY RUN COMPLETE - No changes were made")
        else:
            print("UPDATE COMPLETE")
        print(f"Total removed: {total_removed}")
        print(f"Total copied: {total_copied}")
        print(f"{'='*60}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
