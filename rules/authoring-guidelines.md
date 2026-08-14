# Authoring Framework Guidance — Rules vs Specs vs Skills

> Read this **before** creating or changing a rule, a spec, a skill, or any documented "way of working" in the Ideable framework. It defines *which layer* a piece of guidance belongs to, *where* it physically lives, and *how* the layers relate. (This file is itself a project-level authoring convention → a **rule**, which is exactly what its own decision procedure prescribes.)

## The three layers

Every piece of Ideable guidance belongs to **exactly one** of these. Classify first, then place.

| Layer | It is… | Lives in | Loading | Binding |
|---|---|---|---|---|
| **Rule** | a hard, mandatory constraint honored on (nearly) every task, or a project‑wide convention (naming, structure, workflow, placement) | `rules/` (repo root) | `general-guidelines.md` every task; topic files on demand | Mandatory — overrides skills |
| **Spec** | the authoritative **contract / source of truth** that SOURCES are generated from | `modules/<M>/[<SUB>/]SPECS/…` | on demand, via the module's `base-specs.md` reading‑order chain | Normative — SPECS→SOURCES; precedence‑layered |
| **Skill** | an advisory **method / on‑ramp** for a class of task, that *points at* the specs | `.agents/skills/<name>/` | `description` always‑loaded; body on invoke | Advisory — rules win |

## Decision procedure

Ask, in order — the first "yes" wins:

1. **Is it a hard constraint honored on essentially every task, or a project‑wide convention?** → **Rule** (`rules/`).
2. **Is it the authoritative definition of *what* the system/module must be, from which code is generated, with precedence and per‑module ownership?** → **Spec** (`SPECS/`).
3. **Is it a repeatable *method / decision‑guide / anti‑pattern checklist* that helps an agent *do* a class of task well, and can reference the specs rather than restate them?** → **Skill** (`.agents/skills/`), added sparingly.

When more than one seems to fit, remember the invariant: **specs hold the truth; rules bind; skills index.** Put the content in the spec (or rule) and have the skill *reference* it — never duplicate it.

> Skills and specs are **complementary, not alternatives.** The framework already pairs them: `auth-implementation-patterns` skill + auth specs; `ideable-bugfixing-and-changes` skill + `*_bug_avoider.md` specs; `ideable-ui` skill + the shared UI specs. Do **not** migrate specs into skills — a skill can't be a code‑generating, precedence‑layered, per‑module contract.

## Where exactly (placement map)

**Rules** — `rules/` (repo root, framework‑owned, project‑level):
- `general-guidelines.md` — mandatory every task. Add here **only** if it must be honored on every task; otherwise create/extend a topic file.
- Topic files (on demand): `testing-guidelines.md`, `version-control.md`, this file, … Add a trigger line in `AGENTS.md` § *Reference files* so agents load it when relevant.

**Specs** — `SPECS/`:
- **Framework‑shared** (Ideable‑maintainer‑owned, synced to every remote, never edited in a remote project): `modules/<M>/[<SUB>/]SPECS/ideable-framework-specs/`.
- **Module‑specific** (module‑maintainer‑owned): the remaining files under `SPECS/`, `backend/SPECS/`, `frontend/SPECS/`, `database/SPECS/` (e.g. `module-ui-specs.md`, `module-bl-specs.md`, `datamodel.sql`).
- Precedence: **module‑specific overrides framework‑shared** (e.g. `module-ui-specs > base_specs > shared-ui-specs > shared-ui-widgets-specs`). Reachable from the module's `base-specs.md` chain. Bugs found in testing feed back into `general_bug_avoider.md` / `datamodel_related_bug_avoider.md`.

**Skills** — `.agents/skills/<name>/` is the **canonical** copy (framework‑owned, synced). `.claude/skills` and `.kiro/skills` are **symlinks** to `.agents/skills`, so editing the `.agents/` copy updates them automatically. `.devin/skills` is a **separate real copy** that must be updated in the same change (or via the push/sync script) and kept **byte‑identical** — verify with `shasum` after editing:
- One `SKILL.md` (frontmatter `name` + a trigger `description`) + optional `reference/` files.
- The skill must **reference** the authoritative specs (cite the section/path), not copy their content. Add a pointer in `AGENTS.md` § *Reference files* if it is a primary entry point for a task class.
- **Atomic capability skills.** A skill may be an **atomic capability** that other workflow skills *reference* rather than a standalone workflow (the reference-not-duplicate principle applied skill→skill). Example: `ideable-spec-driven-edit` holds the one safe-edit discipline; `ideable-implement-specs`, `ideable-test-and-fix`, and `ideable-bugfixing-and-changes` all point at it so a change made from any entry point obeys identical rails. Extract an atom only when a discipline is genuinely shared by ≥2 skills — do not atomize for tidiness (every extra skill's `description` is always-loaded; see § *Context & cache discipline*).

## Context & cache discipline (why placement matters)

- `CLAUDE.md → AGENTS.md` is the **always‑loaded prefix** — keep it tiny and stable. Put explanatory / volatile / rare detail in the on‑demand file it governs, bridged by a **one‑line pointer** in AGENTS.md § *Reference files*.
- A **skill's `description` is always‑loaded** (it appears in the skills list every session). So skills must stay **few**; each description must earn its cost by improving task triggering. Pure reference content that's only read on demand belongs in a **spec** (fully on demand) or an **on‑demand rule file** — not a new skill.
- **Never duplicate** guidance across layers; duplication drifts. One source of truth; the others point at it.

## Ownership & propagation

- All three layers are **framework‑owned** and reach remote modules via the standard sync: `scripts/master_only/push-updates-to-module_template-repo.sh` → `scripts/module_only/sync-template-updates.sh`. The folders `rules/`, `.agents/`, and the `ideable-framework-specs/` spec subfolders are in that script's `is_infrastructure` allowlist and in `modules/module_template/SPECS/ideable-framework-specs/infrastructure-file-list.md`.
- **Ideable maintainers** author framework‑level rules, framework‑shared specs, and skills — **only in the main Ideable repo**.
- **Module maintainers** author **module‑specific specs** (and may add module‑local guidance only where the framework permits); they must never edit framework‑owned files in a remote project (see `general-guidelines.md` § host_app / Remote Boundary).
- When you add a **new framework‑owned doc/folder** that must propagate, add it to **both** sync scripts' allowlists and to `infrastructure-file-list.md` in the same change.
