---
name: bugfixing-and-changes
description: Every time that a change or bugfix is needed in the sources or configuration files, this skill should be used to implement the change
---

# Follow these steps

1. Identify the change needed
2. If the change is:
  - related to specification changes, propose to the user to update the specification files, but never change specifications by yourself without confirmation. If the user confirms the change, update the specification files, otherwise, stop.
  - related to configuration or environment variables or source files, implement the change on the codebase, never ever modify the running containers or the deployment or the DIST files.
3. Do not implement fallbacks or workarounds, only implement the requested change. If some pre-condition is not met, ask the user to meet the pre-condition first. 
4. Do not ever implement fallbacks by hardcoding missing data or silently modifying database schemas, just notify what is missing or different from what is expected.

**IMPORTANT**: every change must be effective after the next build/restart of the application (e.g., via the execution of the redeploy.sh script)
  