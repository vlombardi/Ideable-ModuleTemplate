#!/usr/bin/env python3
"""Every model must DECLARE whether it is tenant-scoped. Fail the build when one does not.

Why a build gate rather than a review habit: the failure mode of tenancy is silent. A new table
without `tenant_id` does not raise, does not log and does not fail a test — it simply holds every
customer's rows in one undivided set, and the query that reads it looks exactly like a correct one.
The tenant-scoping work added the column, the filters and the row-level policies to `template_items`; nothing
stopped the next table from being added without any of them.

So the declaration is mandatory and binary. `__tenant_scoped__ = True` means "this table is
partitioned by tenant", and the gate then insists the `tenant_id` column actually exists — a
forgotten column becomes a build failure instead of global data. `__tenant_scoped__ = False` means
"this table is deliberately not partitioned", which is a legitimate answer for reference data, a
framework ledger or a control-plane table. What is not allowed is silence, because silence is
indistinguishable from an oversight, and one of the two readings is a data leak.

Static on purpose. It runs at build time, in validate_modules.sh, where no database exists — and it
reads the source with `ast` rather than importing it, so a module whose settings are absent from the
environment is still checked.

Usage:
    check_tenancy_markers.py <app_dir> [<app_dir> ...] [--module NAME]

Exit status 0 when every model declares its tenancy, 1 otherwise (offenders on stderr).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

MARKER = '__tenant_scoped__'
TENANT_COLUMN = 'tenant_id'


def _is_model(node: ast.ClassDef) -> bool:
    """True when the class is a SQLAlchemy declarative model, i.e. derives from `Base`."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == 'Base':
            return True
        if isinstance(base, ast.Attribute) and base.attr == 'Base':
            return True
    return False


def _assigned_names(node: ast.ClassDef) -> set[str]:
    """Every name assigned in the class body, annotated (`x: Mapped[int] = ...`) or not."""
    names: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _marker_value(node: ast.ClassDef):
    """The declared value of the marker: True, False, or None when it is absent/not a literal."""
    for stmt in node.body:
        targets = (
            [stmt.target] if isinstance(stmt, ast.AnnAssign)
            else list(stmt.targets) if isinstance(stmt, ast.Assign)
            else []
        )
        if not any(isinstance(t, ast.Name) and t.id == MARKER for t in targets):
            continue
        value = stmt.value
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
        return None
    return None


def check_directory(app_dir: Path) -> list[str]:
    """Problems found under `app_dir`, as ready-to-print messages."""
    problems: list[str] = []
    for path in sorted(app_dir.rglob('*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError as exc:
            problems.append(f'{path}: cannot be parsed ({exc})')
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not _is_model(node):
                continue
            names = _assigned_names(node)
            # A mixin or abstract base declares no table, so it has no tenancy to declare.
            if names.intersection({'__abstract__'}) and MARKER not in names:
                continue
            declared = _marker_value(node)
            if MARKER not in names:
                problems.append(
                    f'{path}:{node.lineno}: model {node.name} does not declare {MARKER}. '
                    f'Set {MARKER} = True (and give it a {TENANT_COLUMN} column) if its rows '
                    f'belong to one tenant, or {MARKER} = False, with a comment saying why, if '
                    f'they deliberately do not.'
                )
                continue
            if declared is None:
                problems.append(
                    f'{path}:{node.lineno}: model {node.name} sets {MARKER} to something that is '
                    f'not True or False. The declaration has to be readable without running the '
                    f'code, so it must be a literal.'
                )
                continue
            if declared and TENANT_COLUMN not in names:
                problems.append(
                    f'{path}:{node.lineno}: model {node.name} declares {MARKER} = True but has '
                    f'no {TENANT_COLUMN} column — nothing partitions its rows, so every tenant '
                    f'shares them.'
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app_dirs', nargs='+', type=Path)
    parser.add_argument('--module', default='', help='module name, for the error prefix')
    args = parser.parse_args(argv)

    prefix = f'[{args.module}] ' if args.module else ''
    problems: list[str] = []
    for app_dir in args.app_dirs:
        if not app_dir.is_dir():
            print(f'ERROR: {prefix}not a directory: {app_dir}', file=sys.stderr)
            return 1
        problems.extend(check_directory(app_dir))

    if problems:
        print(f'ERROR: {prefix}every model must declare {MARKER} (True or False):', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
