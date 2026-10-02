---
name: ideable-changelog
description: Draft the CHANGELOG.md section for a framework release — what changed since the previous release tag, grouped by area and kind, for the maintainer to review before publishing.
category: development
displayName: Changelog
---

Draft the `CHANGELOG.md` section for a release, so `publish_framework.sh` — which refuses a release
whose version has no section — has one to find.

**The format is not defined here.** `rules/version-control.md` § *A release says what it contains*
is the contract: the section heading, the four area blocks, the three entry kinds, the three-line
limit and what the links are for. Read it and follow it exactly. This skill is the method for
producing a section that obeys it.

## 1. Establish the range

The section covers everything since the previous release. Resolve the range, never assume it:

```bash
git tag -l --sort=-v:refname | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | head -1   # the previous release
git log --oneline <previous>..HEAD
```

`worklog/*` tags are archives, not releases — exclude them. If no release tag exists, the range is
the whole history and the section says so rather than pretending to a previous version.

## 2. Read what the range actually did

Commit subjects alone produce a changelog that reads like a commit log, which is the failure this
skill exists to avoid. The range's own bookkeeping says what the work *was*:

- `implementation-plans/… (Merged).md` — each merged plan's **Purpose** states what it set out to do
  and why; its **Sub-sets summary** lists the things it actually landed.
- `kanban/done/*.md` — the card each plan came from, usually with the motivating incident.
- `git log <previous>..HEAD` — the floor. A fast-lane change has no plan and no card, so it appears
  only here.

Read the plans first. They are written for a reader; the commits are written for a reviewer.

## 3. Classify each change

Place every entry under the area it changes — *General framework rules*, *host_app*, *Dev Toolbox*,
*Module Template* — and then under *Bug fix*, *Improvement* or *New feature*. Leave out an area or a
kind with nothing in it; an empty heading tells the reader nothing.

Judgement calls the classification needs:
- A change to `rules/`, `scripts/dev/common/` or the dev-cycle is **General framework rules** unless
  it is specifically the toolbox image, which is **Dev Toolbox**.
- A change that a module maintainer will *see* belongs to **Module Template**, even when the edit
  was made in `modules/module_template/`; a change only the framework maintainer sees does not.
- An internal refactor with no consequence for any reader is not an entry. A changelog that lists
  everything is one nobody reads.

## 4. Write the entries

Each entry is **at most three lines**, and is written for someone adopting the version, not for
someone who reviewed the diff:

- **Bug fix** — what was wrong, and how it is fixed where knowing that helps the reader. "Fixed a
  bug in the publish" tells them nothing; "`latest` could name a half-published release when a later
  step failed; it now moves only after every other step succeeds" tells them whether they were
  affected.
- **Improvement / New feature** — what it now does, and a link to the documentation chapter
  describing it. Links do not count toward the three lines. If no chapter describes it, that is a
  documentation gap: say so to the maintainer rather than linking nothing.

## 5. Hand it to the maintainer

Insert the section at the top of `CHANGELOG.md`, below the title and above the previous version.
Then **stop and report**: the range used, the number of entries per area, and any change you could
not classify or could not link. The maintainer reviews the draft before the publish runs — this
skill drafts, it does not decide what a release claims.
