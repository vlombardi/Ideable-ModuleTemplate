---
trigger: on-demand
---

> Load this file for git, commit, branch, or pull-request tasks.

## Version Control


## The remote gate, and how to get past it when you must

`.github/workflows/gate.yml` runs on **every branch and every pull request**: `ruff`, `mypy`, `tsc`
and the **393 tests that need no running stack** (computed by `scripts/common/stack_free_tests.py`,
never a hardcoded list). The integration tests that need Postgres, Authentik, Traefik and Docker stay
local, in `run_enabled_tests.sh`.

Two layers, doing different jobs:

| | catches | can be skipped by |
|---|---|---|
| `.githooks/pre-push` (local, self-enabling) | forgetting to run the suite | `SKIP_TEST_GATE=1`, or a clone with hooks off |
| `gate.yml` (remote) | everything the local layer misses | only a deliberate, recorded override |

Both layers reach **every** project. `.githooks/` is part of the shipped infrastructure set
(`scripts/master_only/push-updates-to-module_template-repo.sh`) and is classified as infrastructure
by the sync, so a remote module project receives the hook and later fixes to it, and
`scripts/common/ensure_hooks.sh` finds a `.githooks/` to point `core.hooksPath` at. Stated because
this table is force-synced and read in those projects: a rule describing a control the reader does
not have is worse than no rule, and `scripts/TESTS/test_documented_controls_reach_remotes.py` now
fails if this row and the shipped set ever disagree again.

### Bypassing the remote gate — deliberately

**A gate that can strand a production hot-fix is a gate that gets deleted**, so there is an escape
hatch and it is meant to be used when it is genuinely needed. It costs one line, and that line is a
**reason**:

```bash
git commit --amend --trailer "Gate-Override: hot-fix for <what broke>, suite re-run to follow"
git push --force-with-lease
```

The job then passes — so branch protection does not block you — but reports the override as a
**warning** with the reason in the run summary. The reason is in git history permanently, which is
what makes this auditable rather than a flag someone quietly flips.

**The failing job prints that command itself.** You do not need to remember it or find this page: it
is in the run summary at the moment it is needed.

A bypass is a **deferral, not a dismissal** — run the full suite once the emergency is over.

## What a fresh clone needs: Docker, and nothing else

Every dev-cycle tool lives in one digest-pinned image. Run any of them through it:

```bash
scripts/dev/tool.sh --doctor                      # assert the image is complete
scripts/dev/tool.sh ruff check modules scripts
scripts/dev/tool.sh mypy modules/host_app/backend/SOURCES/app
scripts/dev/tool.sh pytest -q scripts/TESTS
scripts/dev/tool.sh --shell                       # interactive
```

The first run pulls the image (~2.7 GB, browsers included, once only); after that it is a
`docker exec` into a container that stays up. Verified identical to a host run: same ruff and mypy
verdicts, 123 tests passing in both, **and no skips** — the container has `git`, so the checks that
need it actually run.

**One container per project, named for the project.** The container is `ideable.devtools.<APP_SLUG>`
— `ideable.devtools.acme` for a project whose `project.env.config` sets `APP_SLUG=acme`, falling back
to the repository directory name when that file is absent. Everything that makes a container usable
is derived from the project it was created for: the mount of the repository, the working directory,
the `node_modules` caches, the `--add-host` for `EXTERNAL_BASE_HOST`, and — through `framework.env` —
**which image it runs**. One container shared by two projects therefore either fails to reach the
second project's files or silently runs the first project's toolbox, which is the parity promise
above inverted. Two projects open at once each get their own, and `docker ps` says which is which.
Set `IDEABLE_DEVTOOLS_CONTAINER` to override the name; nothing routine requires it. `tool.sh` never
reuses a container that does not mount the repository it is run from — it recreates it for this
checkout and says which checkout it belonged to, rather than failing later inside `docker exec` with
a message that names neither.

### One active checkout per project, on one host

**A project's deployment is a host-level singleton, and only one checkout may be driving it at a
time.** You may keep as many clones and `git worktree`s as you like; work in one of them at a time.

Nothing in a deployment is namespaced by checkout. Every part of it is keyed by `APP_SLUG` and lives
once on the machine: the published ports in `project.env.config`, the compose project name and its
volumes, and the image names — which § *Development process* step 3 fixes deliberately, *"ensuring
the same image name is produced regardless of which project performs the build"*. Each checkout has
its own `deployment_root/` recipe, and they all deploy into the same host slots, so **the last
deploy wins, host-wide**.

Two consequences worth stating, because neither announces itself:

- **A stack-dependent run only means something if this checkout deployed last.** Otherwise the suite
  is your test code asking questions about another checkout's images, and it answers them without
  complaint.
- **The dev tools container follows the active checkout.** It is a toolbox, not a stack — no ports,
  no images, no volumes — so switching checkouts simply recreates it, which is safe exactly because
  the idle checkout is not using it.
- **The toolbox attaches to this project's stack, or to none.** The suite reaches services by name
  (`http://backend:8001`), which works because the container joins the stack's network — matched on
  the compose project, which is `APP_SLUG`. With no stack running, or no identifiable project, it
  joins nothing: the suite then fails to resolve `backend`, which is the honest answer. Joining
  whichever stack happened to be up would let it ask another project's services and report their
  answers as this project's, and every project here has the same service names.

**What a worktree can do without a deployment of its own** is the stackless half of the cycle, and
it is most of the framework's own work: the framework suite, `ruff`/`mypy`/`tsc`, the docs gate, and
the push gate's bookkeeping and documentation clauses. Those need no `deployment_root/` at all, and
the tooling no longer assumes one exists.

**The container is the toolchain, and routing is the default.** Every shipped script that invokes a
dev tool re-execs itself through `scripts/dev/tool.sh` first, so by the time `pytest`, `ruff`, `mypy`
or `npx` runs, it is the image's copy — `scripts/TESTS/test_shipped_scripts_use_the_container.py`
fails any shipped script that reaches for a host tool instead. A project's only prerequisite is
Docker, and "the tests passed" therefore means the same thing on every machine.

**The escape hatch is `IDEABLE_NO_CONTAINER=1`**, which runs the host toolchain instead. It is for a
machine where Docker is unavailable; it gives up the parity above, so a result obtained that way
proves less.

**Why it exists.** Four defects in two days came from a machine drifting from what the tooling
assumed, each behind a reassuring signal: `pydantic` absent so mypy checked nothing;
`sqlalchemy-continuum` absent so six tests skipped at import for weeks; `PyYAML` absent in CI; and
`.venv/bin/pip` carrying a shebang that pointed at another project's interpreter. A shared list gives
parity by convention. One digest gives parity by construction.

### The Docker socket, and where it must never appear

The container mounts `/var/run/docker.sock` because the dev cycle is itself Docker-driven — 15 files
call `docker compose`, 8 call `docker exec`, 5 call `docker build`. Anything inside it therefore has
root-equivalent control of your Docker.

**Approved for local development only (2026-08-27), and it must never appear in anything deployed.**
This is the same trade the horizontal-scale work examined when it *removed* the socket from Traefik: a deployed service
and a developer's own machine are different calculus, and the deployed side of that decision stands.

## The repo's git hooks enable themselves

You do not need to run anything. `scripts/common/ensure_hooks.sh` is called by
`run_enabled_tests.sh` and `redeploy.sh`, so the first test run or redeploy in a fresh checkout turns
the hooks on and prints that it did.

**Why it has to be automatic.** `core.hooksPath` lives in `.git/config`, which is *not* part of the
repository's content — git deliberately does not ship hooks with a clone, because cloning a repo must
not grant it the right to run code on your machine. The consequence is that a hook protects only the
checkout where someone remembered to switch it on. "Remember to run one command" is precisely the
class of rule that erodes, which is the problem these hooks exist to solve, so it is not left to
memory.

Opt out for one command with `IDEABLE_NO_HOOKS=1`; disable permanently with
`git config --unset core.hooksPath`.

`.githooks/pre-push` refuses a push unless the most recent `TEST_REPORTS` summary says **PASSED**
and **covers the code being pushed**, with a clean tree. A green run of different code proves
nothing about the code being pushed.

"Covers the code" is a question about the **tree**, not the commit id, and it accepts exactly four
things:

1. the summary names HEAD;
2. the summary's commit has the *same tree* as HEAD — the delivery case, a new commit over
   identical code;
3. the trees differ **only** under `implementation-plans/`, `kanban/` or `TEST_REPORTS/`, and the
   three checks that read the plan files pass against HEAD;
4. the trees differ **only** under documentation — `*.md`, `rules/`, `.agents/`, any `SPECS/` — and
   the **whole framework suite** passes against HEAD.

Clauses 3 and 4 verify themselves by running tests from `scripts/TESTS/`, which is the maintainer's
and is deliberately not shipped. In a **remote module project** those tests are therefore absent,
and the hook says so: it prints `DID NOT RUN` and allows the push, rather than reading a missing
suite as a failing one. The distinction is the point — a check that cannot fail must never report
success, and a control that always refuses is one that gets disabled. A broken toolchain is not the
same case: where `scripts/TESTS/` exists and `scripts/dev/tool.sh` cannot run, the push is refused.

Anything else is refused, a target branch that has moved included — that combination was never
tested. A code change sitting alongside a doc change is not clause 4: the difference is then not
docs-only, and the gate refuses it.

Clause 4 exists because `Documenting` runs **after** a green `Testing` by design — documentation is
aligned to what has already been built and tested — so its edits are never inside the recorded run,
and the trees differ on every plan that touches a document. Re-running the full suite to re-certify
a paragraph costs more than it proves. The suite it does run is the whole of `scripts/TESTS`, not a
curated list of doc tests: a curated list is one more thing that quietly stops being complete the
next time someone adds a test that reads a document.

`TEST_REPORTS/` is in that list because the runner records the commit it tested and **then** writes
the summary, so committing the summary necessarily moves HEAD past the commit the report names.
Excluding it made the gate refuse on a difference its own mechanism creates. Nothing executes a
report, so accepting one costs no coverage.

**What makes the tree comparison usable at all:** `scripts/dev-cycle.sh run` commits the working
tree *before* it executes `Testing`, so a recorded run certifies a **commit** rather than a working
tree, and `run_enabled_tests.sh` samples `- Working tree:` **before the first suite starts** — after
the run, that field would describe the reports the run had just written. Both matter to this gate,
and both were wrong until the first real plan delivery was refused by it.

**Keep the repository's own `.gitignore` sufficient.** The suite runs inside the dev tools
container, which has no personal `~/.gitignore_global`, so a path ignored only there is untracked
*in the run* and every summary records `dirty`. `scripts/TESTS/test_a_green_run_certifies_a_commit.py`
compares the repo's rules against the host's and fails when a personal excludes file is doing
load-bearing work.

It exists because on 2026-08-26 a commit was merged and pushed while the runner had exited 1 and
printed `❌ FAILED — 1 failed` on screen. The signal was correct and unread. Override deliberately
when you mean to:

```bash
SKIP_TEST_GATE=1 git push …
```

### Git Workflow

* **Branching Strategy**:
  - **`main`**: the integration and production-ready branch — the default branch and the base for
    pull requests. Never commit to it while standing on it. Two routes land work there, and
    **the maintainer decides which** — the presence of an implementation plan does not decide it:
    - **Directly, as ONE squashed commit — the default, for plan-driven work and fast-lane work
      alike.** A plan owns its `plan/<description>` branch and `deliver` squashes it onto the
      target, pushes, and deletes the branch (§ *Delivering a plan*).
    - **Through a pull request, when review is wanted — `deliver --pr`.** An opt-in, not an
      obligation: a plan is not sent to review because it is a plan, but because the maintainer
      wants it reviewed.
    - **A fast-lane change → pushed to `main` directly.** A change simple enough to need no plan
      (`ideable-bugfixing-and-changes` § *First — plan or fast lane?*, where the maintainer decides)
      is committed on a short-lived branch and pushed. No PR, no review: routing a one-line fix
      through a plan and a review costs more than the fix, and a process more expensive than its
      subject gets skipped rather than followed. Its only check is the two gates below — which is
      exactly why neither is ever bypassed for it, and why the fast lane still runs the tests and
      aligns the docs when they are needed.
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

### Delivering a plan (mandatory)

A plan reaches `Done` green and committed on its `plan/<description>` branch, and **unlanded**.
Landing it is a step of the dev-cycle — the `Merged` node — performed by:

```bash
./scripts/dev-cycle.sh deliver --dry-run              # compose and print the message; change nothing
./scripts/dev-cycle.sh deliver                        # confirm, squash onto main, push
./scripts/dev-cycle.sh deliver --target release/1.4   # default target is main
./scripts/dev-cycle.sh deliver --yes --push           # unattended, both decisions pre-granted
./scripts/dev-cycle.sh deliver --pr                   # open the PR instead; target untouched
```

**One commit per plan, and it is a squash.** The intermediate history a plan produces — implement A,
fix A, add B, fix the regression in A, plus the router's own `chore(dev-cycle)` checkpoints — is not
useful on a shared branch, and 11.6% of `main` was those checkpoints when this was measured. It does
not reach the target at all. On the direct route `deliver` deletes the plan branch after the
push, because git does not record a squash as merged and a surviving branch would re-apply on
a second run. With `--pr` the branch is kept: it *is* the pull request, and GitHub deletes it
on merge when the repository is configured to.

**The plan artifact is what survives.** It is tracked, and `deliver` writes its final `(Merged)`
version into the delivered commit before squashing, so the per-thing detail outlives the branch. The
`Plan:` trailer points at it.

**The message.** Subject in the mandatory format above — not git's default `Merge branch '…'`, not a
`Merge:` prefix. Body: what the plan set out to do, what it delivered, what it deliberately did not,
and the evidence.

```
<type>(<scope>): <what the plan delivered>            ← ≤72 chars

<Purpose, condensed to 1–4 lines>

Delivered:
- <sub-set 1 description>
  - <thing>
  - <thing>
- <sub-set 2 description>
  - <thing>
Deferred (⏭️): <thing> — <who decided, and why>
Blocked (⛔): <thing> — <the blocker>

Tests: <p> passed / <f> failed / <s> skipped (<summary timestamp>)
Files: <n> changed across <areas>
Sub-sets: <n>

Plan: implementation-plans/<file>
Kanban: kanban/done/<card>.md
Test-Report: TEST_REPORTS/<ts>-SUMMARY.md
```

- **One bullet per sub-set, every thing beneath it, uncapped.** The plan branch is deleted, so the
  message is where a reader meets the detail first. Measured worst case on the largest plan on
  record — 7 sub-sets, 35 things — is a 47-line body.
- **⏭️ and ⛔ are never omitted.** They are decisions, and a summary that drops them makes a partial
  delivery read as "everything asked for was done", at the most visible point in the history.
- **Prose comes from the plan; every number comes from a measurement.** Test counts from the
  `TEST_REPORTS` summary, file counts from `git diff --name-only`, the sub-set count from the plan's
  table. The plan's ✅ marks are never the source of the `Tests:` line — a plan is a status artifact.

**Opening the pull request — `deliver --pr`.** When the maintainer wants review, work reaches
`main` through a pull
request (§ *Git Workflow*), and that is what this flag does:

```bash
./scripts/dev-cycle.sh deliver --pr          # bookkeeping commit, push the branch, open the PR
```

It makes the same `(Merged)` plan + kanban bookkeeping commit **on the branch**, pushes the branch,
and opens the PR with the composed subject as its title and the rest as its body. The target is
**not** modified and the branch is **not** deleted — the branch *is* the pull request, and GitHub
creates the delivered commit at merge time. Needs `gh`.

**Merge it with the command `--pr` prints, not with the green button.** GitHub's squash-merge does
not reuse the branch's message: the subject defaults to `<PR title> (#N)` and the body to a
concatenation of the branch's commits. That breaks two of the checks above — ` (#N)` eats into the
72-character subject, and the `Plan:` / `Kanban:` / `Test-Report:` trailers are replaced by whatever
the router's checkpoints said. So the message is written to `.git/IDEABLE_DELIVERY_MSG` and the
merge is driven as:

```bash
gh pr merge <pr> --squash --subject '<subject>' --body-file .git/IDEABLE_DELIVERY_MSG
```

**A moved target is refused, not merged.** The `Tests:` and `Files:` numbers were measured against
the branch's tree. The direct route squashes immediately, so the two cannot drift; a review window
is exactly the gap where they can. If `<target>` or `origin/<target>` carries a commit the branch
does not, `--pr` stops and tells you to rebase and re-run the suite.

`deliver` without `--pr` remains the direct route: it creates the squash on the target itself and
pushes. It is the path for work the maintainer is not sending to review — and for a fast-lane change
no plan exists, so neither route applies (§ *Git Workflow*).

**Reading it back.** `git log --oneline main` is one line per plan and one per fast-lane change, and the plans are the commits carrying a `Plan:` trailer:

    git log --format='%h %(trailers:key=Plan,valueonly)' main

`git log --format='%(trailers:key=Plan,valueonly)' main` maps every delivery to its plan file.

Enforced by `scripts/TESTS/test_plan_deliveries_say_what_they_did.py`, over commits carrying a
`Plan:` trailer.

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
  - Per-run test report detail (`TEST_REPORTS/*/`) — regenerated by every run; the
    cross-module `TEST_REPORTS/<timestamp>-SUMMARY.md` stays tracked, because a delivery's
    `Test-Report:` trailer is checked against it
  - Docker volumes and data directories
