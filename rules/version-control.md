---
trigger: on-demand
---

> Load this file for git, commit, branch, or pull-request tasks.

## Version Control

### Git Workflow

* **Branching Strategy**:
  - **`main`**: the integration and production-ready branch — the default branch and the base for pull requests. Never commit directly to `main`; always work on a branch and open a PR.
  - **Feature branches**: `feature/<module>-<description>` (e.g., `feature/cam-user-auth`)
  - **Bugfix branches**: `bugfix/<module>-<description>` (e.g., `bugfix/esp-kafka-connection`)
  - **Hotfix branches**: `hotfix/<description>` (for urgent production fixes)
  - Long-lived integration branches for large, multi-phase efforts (e.g. `hardening/<topic>`) may be cut from `main` when a plan calls for it; phase branches then merge into that integration branch before it is promoted to `main`.

* **Branch Lifecycle**:
  1. Create a feature/bugfix branch from `main`
  2. Implement the change with regular commits
  3. Open a pull request (PR) to merge back into `main`
  4. Code review and testing
  5. Merge to `main` after approval
  6. Delete the branch after merge

### Commit Guidelines

* **Commit Message Format**:
  ```
  <type>(<module>): <short description>

  <detailed description if needed>

  <references to issues/tickets if applicable>
  ```

* **Commit Types**:
  - `feat`: New feature
  - `fix`: Bug fix
  - `docs`: Documentation changes
  - `style`: Code style changes (formatting, no logic change)
  - `refactor`: Code refactoring
  - `test`: Adding or updating tests
  - `chore`: Maintenance tasks (dependencies, build, etc.)

* **Examples**:
  ```
  feat(cam-backend): add user authentication endpoint
  fix(esp-flink): resolve kafka connection timeout
  docs(general): update testing guidelines
  ```

### Pull Request Process

* **PR Requirements**:
  - Clear title and description
  - Reference to related issues/tickets
  - All tests passing
  - Code review approval from at least one team member
  - Updated documentation if appropriate
  - Updated `SPECS/dependencies.md` if applicable

* **Review Checklist**:
  - Code follows project guidelines
  - Tests are comprehensive
  - No security vulnerabilities introduced
  - Breaking changes are documented
  - Module dependencies are correctly declared

### Breaking Changes

* **Definition**: Changes that break backward compatibility or require modifications in dependent modules
* **Process**:
  1. Clearly document the breaking change in PR description
  2. Update the relevant module base spec, typically `SPECS/ideable-framework-specs/base-specs.md`, with migration notes
  3. Coordinate with owners of dependent modules
  4. Plan migration strategy before merging
  5. Version appropriately (follow semantic versioning)

### .gitignore Best Practices

* **Always Ignore**:
  - Build artifacts (contents of `DIST/` folders)
  - Environment files with secrets (`.env.secrets`, `project.env.secrets`, not `.env.config` or `.env.*.example`)
  - IDE-specific files (`.vscode/*`, `.idea/*`, except shared configs)
  - Dependency directories (`node_modules/`, `__pycache__/`, `target/`)
  - Test reports (unless specifically archived)
  - Docker volumes and data directories
