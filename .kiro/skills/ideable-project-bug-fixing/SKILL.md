---
name: ideable-project-bug-fixing
description: Ideable project bug fixing expert. Use whenever a bug is found to follow a consistent process ensuring the spec driven approach is kept over iterations.
category: bug-fixing
color: blue
displayName: Bug Fixing Expert
---

When a bug is found in the Ideable project, use this skill to fix it.

Ideable Project is:
- based on specification and test driven development
- divided in modules and sub-modules, each with its own specifications and tests.
- Specifications are located in the `SPECS` folder of each module or sub-module, and each `SPECS` folder contains a:
  - (mandatory) `base-specs.md` file with the base specification
  - (optional) `general_bug_avoider.md` file with the bug avoider specification
  - (optional) `<OTHER_ASPECT>_bug_avoider.md` file with the bug avoider specification for a specific aspect of the module or sub-module (e.g., `database_bug_avoider.md`, `ui_bug_avoider.md`, `api_bug_avoider.md`, etc.)
  
**IMPORTANT**: When fixing a bug, first of all look for a possible solution in the `general_bug_avoider.md` file, then in the `<OTHER_ASPECT>_bug_avoider.md` files.

**IMPORTANT**: If you find a bug and find a fix, first of all understand if the bug derives from a missing specification in the `base-specs.md` file, and if so, add it there. Otherwise, add the fix to the appropriate `general_bug_avoider.md` or `<OTHER_ASPECT>_bug_avoider.md` file.
