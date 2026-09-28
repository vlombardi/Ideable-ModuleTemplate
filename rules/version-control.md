---
trigger: on-demand
---

> Load this file for git, commit, branch, or pull-request tasks.

## Version Control


## The remote gate, and how to get past it when you must

`.github/workflows/gate.yml` runs on **every branch and every pull request**: `ruff`, `mypy`
and the stack-free tests (computed by `scripts/dev/common/stack_free_tests.py`, never a hardcoded
list). The integration tests that need Postgres, Authentik, Traefik and Docker stay local, in
`run_enabled_tests.sh`. A frontend `tsconfig.json`'s own static gate (`tsc --noEmit`) is enforced
by `scripts/TESTS/test_a_generated_tsconfig_avoids_deprecated_options.py`, part of that stack-free
set, rather than by a dedicated `tsc` step in the workflow.

Two layers, doing different jobs:

| | catches | can be skipped by |
|---|---|---|
| `.githooks/pre-push` (local, self-enabling) | forgetting to run the suite | `SKIP_TEST_GATE=1`, or a clone with hooks off |
| `gate.yml` (remote) | everything the local layer misses | only a deliberate, recorded override |

Both layers reach **every** project. `.githooks/` is part of the shipped infrastructure set
(`scripts/dev/master/push-updates-to-module_template-repo.sh` — which ships **everything under
`scripts/` except `dev/master/` and `TESTS/`**, one exclusion rather than an allowlist, so what a
project receives is decided by which folder a file sits in) and is classified as infrastructure
by the sync, so a remote module project receives the hook and later fixes to it, and
`scripts/dev/common/ensure_hooks.sh` finds a `.githooks/` to point `core.hooksPath` at. Stated because
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

## What a fresh clone needs: Docker, and a host `python3`

Every dev-cycle tool lives in one digest-pinned image. Run any of them through it:

```bash
scripts/dev/common/tool.sh --doctor                      # assert the image is complete
scripts/dev/common/tool.sh ruff check modules scripts
scripts/dev/common/tool.sh mypy modules/host_app/backend/SOURCES/app
scripts/dev/common/tool.sh pytest -q scripts/TESTS
scripts/dev/common/tool.sh --shell                       # interactive
```

The first run pulls the image (~2.7 GB, browsers included, once only); after that it is a
`docker exec` into a container that stays up. Verified identical to a host run: same ruff and mypy
verdicts, 123 tests passing in both, **and no skips** — the container has `git`, so the checks that
need it actually run.

**One container per project, named for the project.** The container is `ideable.devtools.<APP_SLUG>`
— `ideable.devtools.acme` for a project whose `project.env.config` sets `APP_SLUG=acme`, falling back
to the repository directory name when that file is absent. Everything that makes a container usable
is derived from the project it was created for: the mount of the repository, the working directory,
the `node_modules` caches, the `--add-host` for `EXTERNAL_BASE_HOST`, and — through `framework.env` and
`framework.lock.json` — **which image it runs**: the one line in `framework.env` names the framework
version, the lock records the digest published for it, and the image is pulled by that digest, never
by a moving tag and never built locally. One container shared by two projects therefore either fails to reach the
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
dev tool re-execs itself through `scripts/dev/common/tool.sh` first, so by the time `pytest`, `ruff`, `mypy`
or `npx` runs, it is the image's copy — `scripts/TESTS/test_shipped_scripts_use_the_container.py`
fails any shipped script that reaches for a host tool instead. A project's prerequisites are Docker
and a host `python3` — the latter only to run `scripts/runtime/framework_version.py`, the one reader of
`framework.env` and `framework.lock.json` that tells `tool.sh` which image to pull — and "the tests
passed" therefore means the same thing on every machine.

**Two checks enforce that, not one, and the second exists because the first cannot see everything.**
`test_shipped_scripts_use_the_container.py` recognises a *named* dev tool in command position —
`pytest`, `ruff`, `npx` — which is a deliberately narrow detector, because one that flagged every
interpreter would cry wolf and get exempted into uselessness. A script whose tool is a **bare
interpreter** is invisible to it, and `./dev-cycle.sh` was exactly that: it ran the router on the
host, so driving an LLM node needed the Agent SDK installed *there*, and nothing objected. Its
routing is pinned by name instead, in
`scripts/TESTS/test_the_agent_ships_with_the_toolbox.py`. A rule whose enforcement is named should
name the enforcement it actually has.

**The escape hatch is `IDEABLE_NO_CONTAINER=1`**, which runs the host toolchain instead. It is for a
machine where Docker is unavailable; it gives up the parity above, so a result obtained that way
proves less.

**The container keeps the host's clock, not its own.** The image is `Etc/UTC`, and every naive
timestamp a shipped tool writes — `dev-cycle.sh`'s `Created at`/`Last updated`, a plan's own
filename — is `datetime.datetime.now()`, which follows `TZ` but defaults to UTC when nothing sets
it. `scripts/dev/common/tool.sh` resolves the host's zone from `/etc/localtime` (a tzdata NAME, not
the `CEST`-style abbreviation `date +%Z` gives, which carries no DST rules) and forwards it as `TZ`
at container **creation** — fixed like the credential wiring, because it shapes every tool in the
image and the container is reused across commands, not recreated per one. A host whose zone cannot
be resolved leaves the container at its own `Etc/UTC` default rather than being handed an empty
value. On 2026-09-25 a plan updated at 17:40 CEST recorded `15:40` before this.

### The agent runs in the toolbox too, and its version is the image's

The dev cycle's LLM nodes are driven by an agent, and an agent is a dev tool like `ruff` or
`pytest`: its behaviour decides what a node produces, so a machine running a different one runs a
different cycle. It is therefore in the image, at a pinned version, and `--doctor` asserts it —
`claude` in `REQUIRED_TOOLS`, `claude_agent_sdk` in `REQUIRED_PYLIBS`.

`./dev-cycle.sh` re-execs through `scripts/dev/common/tool.sh` like every other shipped script, so
the router and the agent it drives both run in the container. **Driving a plan therefore needs
nothing installed on the host** — which is what the rule above has always promised and what this one
script quietly did not deliver: it resolved a host interpreter, so an LLM node needed
`claude_agent_sdk` importable *there*, and `--deterministic` cannot leave `Implementing`.

**Your credential is forwarded, never mounted and never baked in.** Mint one once with
`claude setup-token` and export `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`); `tool.sh`
forwards either into the container the way it forwards its other named variables. There is no
credentials file in the image and none is mounted: this container holds the Docker socket, so
anything reaching it is root-equivalent on your Docker, and a long-lived credentials file is the
wrong thing to put there. It is also the only route that works on every platform — on macOS the
credential is a login-Keychain item, not a file, so there would be nothing to mount. With neither
variable set the router refuses the node and names the command, rather than letting the CLI fail
with an auth error two layers from the cause.

**Both halves, always.** The Python package is a thin wrapper that locates a Node CLI on `PATH` and
spawns it. An image carrying only the package passes an import check and fails at the first node,
which is precisely the silently-weakened check this container exists to remove — so the doctor
asserts the binary and the library separately, the way it already does for `alembic`.

**State the consequence rather than let it be discovered: the agent's version is pinned by the
image, so it moves when the framework release moves.** A fix in the CLI reaches a project when that
project adopts a framework release, not when it runs `npm update`; and a project pinned to `X.Y.Z`
is pinned to that release's agent as surely as to its host_app images. This is a coupling the
framework accepts deliberately — it is the same trade as every other tool in the image, and the
alternative is an agent version that varies per machine, which is the drift the toolbox exists to
end. Where it bites, the remedy is the ordinary one: adopt a newer release, or use
`IDEABLE_NO_CONTAINER=1` and accept that the result proves less.

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

You do not need to run anything. `scripts/dev/common/ensure_hooks.sh` is called by
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

"Covers the code" is a question about the **tree**, not the commit id, and it accepts exactly three
things:

1. the summary names HEAD;
2. the summary's commit has the *same tree* as HEAD — the delivery case, a new commit over
   identical code;
3. the trees differ **only** under exempt paths — bookkeeping (`implementation-plans/`, `kanban/`,
   `TEST_REPORTS/`, `framework.env`, `framework.lock.json`) and/or documentation (`*.md`, `rules/`,
   `.agents/`, any `SPECS/`) — and the **whole framework suite** passes against HEAD.

Bookkeeping and documentation share one clause, not two. Until 2026-09-25 bookkeeping had its own
clause that re-ran a hand-curated list of "the checks that read the plan files" instead of the whole
suite, and that list did not include every test that reads a plan: a fold left a row unmeasured, a
hand-fix looked bookkeeping-only from `deliver`'s own certifier (§ *Delivering a plan* below), and
only this hook's narrower, separately-curated list caught the gap — after the squash had already
landed locally. The fix already existed one clause over: the documentation exemption had rejected a
curated list for the identical reason a release earlier — *a curated list is one more thing that
quietly stops being complete the next time someone adds a test that reads it* — and re-ran the
**whole** `scripts/TESTS` instead. Bookkeeping now gets that same answer, so there is one exemption,
one re-verification, not two hand-maintained ideas of what "safe to skip" means.

This clause verifies itself by running tests from `scripts/TESTS/`, which is the maintainer's and is
deliberately not shipped. In a **remote module project** those tests are therefore absent, and the
hook says so: it prints `DID NOT RUN` and allows the push, rather than reading a missing suite as a
failing one. The distinction is the point — a check that cannot fail must never report success, and
a control that always refuses is one that gets disabled. A broken toolchain is not the same case:
where `scripts/TESTS/` exists and `scripts/dev/common/tool.sh` cannot run, the push is refused.

Anything else is refused, a target branch that has moved included — that combination was never
tested. A code change sitting alongside a bookkeeping or doc change is not this clause: the
difference is then not exempt-only, and the gate refuses it.

The re-run exists because both kinds of edit land **after** the recorded `Testing`, by design —
`Documenting` aligns documentation to what has already been built and tested, and a delivery's own
bookkeeping (the plan re-stamped, the kanban card moved, the report itself) is written after the
suite that certifies it — so the trees differ on every plan that touches either, which is most of
them. Re-running the full suite to re-certify a paragraph or a moved card costs more than it proves.
The suite this clause runs is the whole of `scripts/TESTS`, not a curated list: a curated list is one
more thing that quietly stops being complete the next time someone adds a test that reads a plan, a
card or a document.

That run is unrecorded, so its verdict is **cached locally** in `.ideable-work/framework-suite-green`,
one git tree hash per line. A push of a tree already proven green says so and does not re-run —
`deliver --pr`, the merge and a retry after a rejected push were each paying the full suite again
over identical content. Keyed on the tree rather than the commit, so an amend or a reword still
hits, and so it is self-invalidating: a change to the suite is a change to the tree. Consulted only
with a clean working tree, because HEAD's tree is not what would be tested when there are
uncommitted changes. When the cache answers, the hook says the suite *already passed* — it never
prints that it is re-running and then serves a record.

`TEST_REPORTS/` is in that list because the runner records the commit it tested and **then** writes
the summary, so committing the summary necessarily moves HEAD past the commit the report names.
Excluding it made the gate refuse on a difference its own mechanism creates. Nothing executes a
report, so accepting one costs no coverage.

**What makes the tree comparison usable at all:** `scripts/dev/common/dev-cycle.sh run` commits the working
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

      **It is visible while it runs, and it holds the checkout.** `dev-cycle.sh fastlane-start
      <description>` takes the checkout's lock, checks out `fix/<description>`, and puts a card in
      `kanban/doing/` — writing one when the work started from no card, moving the given card when
      it did. `dev-cycle.sh fastlane-land <description>` moves that card to `kanban/done/` carrying
      the commit sha, and releases the checkout. The sha and date go INSIDE the card: a dated
      filename is the plan convention, where the router re-stamps it at every transition.

      Three artifacts, one question each — the branch says *what is running* and is derived from
      real state rather than declared; the card shows it on the board; the lock refuses a second
      worker, whether that is another fast lane or a plan's `run`.
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
./scripts/dev/common/dev-cycle.sh deliver --dry-run              # compose and print the message; change nothing
./scripts/dev/common/dev-cycle.sh deliver                        # confirm, squash onto main, push
./scripts/dev/common/dev-cycle.sh deliver --target release/1.4   # default target is main
./scripts/dev/common/dev-cycle.sh deliver --yes                  # unattended: --yes grants both decisions
./scripts/dev/common/dev-cycle.sh deliver --pr                   # open the PR instead; target untouched
```

**One commit per plan, and it is a squash.** The intermediate history a plan produces — implement A,
fix A, add B, fix the regression in A, plus the router's own `chore(dev-cycle)` checkpoints — is not
useful on a shared branch, and 11.6% of `main` was those checkpoints when this was measured. It does
not reach the target at all. On the direct route `deliver` deletes the plan branch after the
push, because git does not record a squash as merged and a surviving branch would re-apply on
a second run. It deletes it **on origin only when it is there** — nothing in the dev-cycle pushes a
plan branch, so "it was never on origin" is the normal case — and it **reports each deletion
separately** rather than claiming both: a failed local delete is a warning naming the re-apply it
would cause, because a line that says the cleanup worked regardless of whether it did is worth less
than no line at all. With `--pr` the branch is kept: it *is* the pull request, and GitHub deletes it
on merge when the repository is configured to.

**A delivery certifies itself, and lands only on green.** `deliver` compares HEAD's tree with the
commit the newest recorded run names. When they differ in any path that is not run bookkeeping —
`implementation-plans/`, `kanban/`, `TEST_REPORTS/` — it **runs the suite itself** and refuses on
red. So delivering a plan needs no manual test run and no `SKIP_TEST_GATE`: the command that needs
the certificate is the one that produces it.

**A bookkeeping-only diff is re-verified, not skipped.** Until 2026-09-25 this branch returned
certified unconditionally — bookkeeping paths record a run rather than being the work it did, so
nothing there seemed able to make a tested tree untested. But the plan file living under
`implementation-plans/` is itself read by tests (`scripts/TESTS/test_plan_rows_are_attributable.py`
among them), and a fold or a hand-fix between the recorded run and `deliver` can change what those
tests say without changing whether `deliver` believed the tree was still green. `framework_suite_certified()`
closes that: on a bookkeeping-only diff `deliver` now re-runs `scripts/TESTS` against HEAD — sharing
the same tree-hash cache `.githooks/pre-push` writes (§ *The repo's git hooks enable themselves*
above), so the common case, a delivery right after a green `Testing` with nothing but bookkeeping
changed since, still costs nothing.

- **Two orderings are forced, and both matter.** The tree is **committed before the run** — a dirty
  tree is refused, so HEAD is a commit and the report certifies it instead of a working tree tied to
  nothing — and the **report is committed after it**, so the tree that reaches the target carries its
  own certificate rather than being dirtied by the run that proved it.
- **A refusal costs nothing.** The check runs before any of the delivery's own bookkeeping: the plan
  is still `Done`, the kanban card has not moved, the target is untouched. That is the point of
  running it here rather than leaving it to the push, which refuses only once the delivered commit
  is already on the shared branch.
- **A PRE-FLIGHT runs before the squash.** `deliver` checks that the target branch exists on origin
  and that a push credential route exists (an SSH agent with a key, `GH_TOKEN`/`GITHUB_TOKEN`,
  `gh auth`, or a configured `credential.helper`). A failure refuses before the squash rather than
  landing a local commit that cannot be pushed — which leaves the maintainer holding a local target
  and two hand commands. The pre-flight is skipped for `--pr`, where the moved-target check above
  already covers reachability.
- **The verdict comes from the process that would push, not from where the command started.** The
  credential check above only tells you a route EXISTS here; `git ls-remote` tells you git can
  actually authenticate, and it is git's answer that decides. The two disagreed once: a forwarded
  token satisfied the first check while the container it ran in had been created before any token
  existed, so it carried no helper to turn the token into a credential — and the refusal blamed the
  network, which was the one thing working. An authentication failure is now reported as one,
  quoting git, and names recreating the toolbox as the way out.
- **Git never prompts the router.** `GIT_TERMINAL_PROMPT=0` is set on every git subprocess the
  router starts, so a missing credential is an error with a message instead of a prompt that cannot
  succeed and hangs an unattended run forever. The router has no tty to answer a prompt with, so
  the prompt is always a hang.
- The newest run is chosen **by filename**, exactly as the push gate chooses it — a checkout rewrites
  every tracked report's mtime, and a delivery that certified one run while the gate read another
  could not certify anything.
- **`deliver` may be stricter than the gate, never looser.** The gate additionally forgives
  `framework.env` and `framework.lock.json`, because a release commit is bookkeeping in the same
  sense; `deliver` lands plans and never releases, so it does not. Forgiving less costs at most one
  suite run that was not needed; forgiving more lands a commit the push then refuses.
- **The push then meets the same bookkeeping-or-docs clause `deliver` itself just satisfied.** The
  report `deliver` commits names the tree it certified, and everything added after it — that report,
  the plan renamed `(Merged)`, the kanban card moved — is bookkeeping. If `deliver`'s own
  bookkeeping-only re-run just ran `scripts/TESTS` against this tree, it recorded the verdict in the
  cache the two share, so the push finds it already proven green and does not pay for it twice.
- **A push failure names what it already left behind.** By the time `deliver` attempts the push, step
  1's bookkeeping has already run: the plan is renamed `(Merged)` and its `ACTIVE PLAN` link is
  dropped, on the branch, before the squash. If the push then fails — network, credentials, a push
  gate refusal, a moved remote — that bookkeeping is **not** rolled back: the delivered commit already
  exists on `target` (`test_every_failure_path_after_the_bookkeeping_rolls_it_back` scopes rollback to
  failures *before* the squash lands, deliberately, because a commit that has landed really did
  happen), and the plan branch is kept specifically so the push has something to retry. What was
  missing until 2026-09-25 was telling the operator the `ACTIVE PLAN` link is gone: without it,
  `status`/`resume` cannot see the plan at all until the link is restored, and the fix — `ln -sfn` —
  already existed for the identical lost-link case in `start`'s own refusal. The push-failure message
  now states the link was dropped and prints the exact command to restore it.

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

- **One `Kanban:` trailer per card the plan implemented**, which is often more than one: the cards a
  plan names in its `Kanban:` header move with it, and a single trailer would record one of them and
  leave the rest unfindable from the landing commit. `rules/implementation-plan.md` § *The kanban
  card moves with the plan* defines the declaration and the refusal that guards it.

- **One bullet per sub-set, every thing beneath it, uncapped.** The plan branch is deleted, so the
  message is where a reader meets the detail first. Measured worst case on the largest plan on
  record — 7 sub-sets, 35 things — is a 47-line body.
- **⏭️ and ⛔ are never omitted.** They are decisions, and a summary that drops them makes a partial
  delivery read as "everything asked for was done", at the most visible point in the history.
- **Prose comes from the plan; every number comes from a measurement.** Test counts from the
  `TEST_REPORTS` summary, file counts from `git diff --name-only`, the sub-set count from the plan's
  table. The plan's ✅ marks are never the source of the `Tests:` line — a plan is a status artifact.
- **`<type>` is measured from the branch's own commits, and never from the router's.** The
  checkpoints (`chore(dev-cycle)`), the plan writes (`docs(plan)`) and the delivery's own certifying
  commit (`chore(tests): the run that certifies …`) are excluded: what the router recorded about a
  run says nothing about what the run did. When nothing but those remains — the ordinary shape of a
  plan driven through `run`, whose code rides in checkpoints — the type is inferred from the paths
  the branch touched instead.
- **The subject a dry run prints is the subject that lands.** It is measured once, before the
  delivery commits anything of its own, so the two cannot disagree. They did once: `856f16ad`
  landed as `chore(tests)` after `--dry-run` had shown `fix(framework)`, because the measurement ran
  after certification and sampled the certifying commit.

**Opening the pull request — `deliver --pr`.** When the maintainer wants review, work reaches
`main` through a pull
request (§ *Git Workflow*), and that is what this flag does:

```bash
./scripts/dev/common/dev-cycle.sh deliver --pr          # bookkeeping commit, push the branch, open the PR
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

### A release says what it contains

`CHANGELOG.md`, at the repository root, is the one place a release states what changed in it. It is
cumulative and it is never purged — it is the record that makes removing the rest safe, and a reader
on `main` can see the whole release history without walking tags.

- **One section per released version, newest first**, headed `## <version> — <date>`. `latest` is a
  channel and not a release: it writes no section.
- **Within a version, one block per area** — *General framework rules*, *host_app*, *Dev Toolbox*,
  *Module Template* — and within each block, *Bug fix*, *Improvement*, *New feature*. An area or a
  kind with nothing to report is left out rather than written empty.
- **Each entry is at most three lines.** A bug entry says what was wrong and how it is fixed, where
  knowing that helps the reader; an improvement or a feature entry links the documentation chapter
  describing it. Links do not count toward the three lines.
- **It is authored before the publish, never by it.** Summarising a range of commits into prose with
  documentation references is not a deterministic operation, so `publish_framework.sh` does not
  attempt it: the `ideable-changelog` skill drafts the section from the range since the previous
  release tag, and the maintainer reviews it. The publish only **refuses** a release whose version
  has no section. A script that generated a heading to satisfy its own gate would teach every reader
  to ignore the gate.
- **It reaches the reader it is written for.** A module maintainer receives the framework through the
  template repository, which copies by an explicit allowlist in
  `push-updates-to-module_template-repo.sh`; `CHANGELOG.md` is on that list. The bookkeeping folders
  are not, and never have been — which is why a module's board is already free of the framework's.

### A release archives how it was made, and hands back a clean tree

A release leaves **two tags**, and they answer different questions. `worklog/<version>` answers *how
this release was reached*; `<version>` answers *what it is*. The worklog is an ancestor of the
release tag, so nothing is lost by the second being smaller than the first.

The sequence, for a release only — `latest` is a channel and does none of it, because the channel is
the loop shared with a remote while a release is still being settled, and compacting on it would
destroy the in-flight working set:

1. the release commit carries `framework.env`, `framework.lock.json` and `CHANGELOG.md`;
2. **`worklog/<version>`** is tagged on it, carrying `kanban/`, `implementation-plans/` and
   `TEST_REPORTS/` in full;
3. a purge commit removes the bookkeeping;
4. **`<version>`** is tagged on the purge commit, and `main` is left there, ready for the next cycle.

**What is purged is the set this repository already defines as bookkeeping** — `BOOKKEEPING_PATHS`,
shared by `.githooks/pre-push`, `run_enabled_tests.sh` and `dev_cycle.py`: `implementation-plans/`,
`kanban/` and `TEST_REPORTS/`. Reusing that set rather than writing a fourth one is what keeps the
four from drifting, and it is also why the release tag's tree is *test-equivalent* to the worklog's:
those paths are already, by the repository's own definition, outside the code under test.
`framework.env` and `framework.lock.json` are in that set for the pre-push gate and are never purged.

**What survives**, besides `CHANGELOG.md`, which is cumulative and never purged:

- `implementation-plans/` — only `(Merged)` plans go. `(Done)` means green but **unlanded**, so
  removing one would delete live work.
- `TEST_REPORTS/` — the most recent `*-SUMMARY.md` stays, because `.githooks/pre-push` reads
  `sort | tail -1` and a repository holding none refuses every push. `AGENT-RUNS.md` stays: it is a
  cumulative log, not a run artifact.
- `kanban/` — only `done/` is emptied. `todo/` and `backlog/` are the next release's input.

**A non-empty `kanban/doing/` refuses the publish.** A card sits there exactly while its plan is in
flight, so publishing would tag a release whose work is half-landed, and the worklog would archive a
card describing unfinished work as if it were history. The publish **reports and stops**; it never
resolves a card itself. The maintainer lands the plan (`dev-cycle.sh deliver` moves the card to
`done/`), moves the card to `todo/` or `backlog/`, or reverts the work — the revert being its own
change, made before the publish and never inside it, since a revert is code that must be tested and
the publish refuses a dirty tree. Until one of those is done, the publish stays refused.

**Retrieving the detail** is `git show worklog/<version>:<path>` — for example
`git show worklog/1.6.10:kanban/done/`. Documents that need to point at a purged path cite it that
way rather than by a bare repository path, which stops resolving at the first compaction.

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
