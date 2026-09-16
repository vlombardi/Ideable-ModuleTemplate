# update-deployable.sh specification

## Purpose
Update any Git-backed deployable repository to a configured remote branch while preserving local runtime configuration.

## Contract
- Accept an optional repository path, `--dry-run`, `--keep-local`, `--force`, and help flags.
- The target path must be a Git repository; use `REMOTE` (default `origin`) and `BRANCH` (default `main`).
- Fetch the configured remote branch and report whether the local repository is behind, ahead, or diverged.
- By default, if the local HEAD equals the remote HEAD, exit immediately with "Up to date" — no reset or merge is performed.
- When `--force` is passed, skip the up-to-date short-circuit even if local and remote commits are identical. Proceed with the full env-merge pass so that env var value changes (local edits not yet committed) are reconsidered.
- Before resetting, snapshot every existing `.env.config` and `.env.secrets` file anywhere in the repository, including files not changed upstream. Also include env paths introduced by the remote update.
- Reset non-environment files to the remote commit.
- For every env file present locally and remotely, merge the remote template with the local file:
  - preserve local values for existing conflicting keys after an interactive choice;
  - add keys introduced by the remote template;
  - report keys removed by the remote template and do not restore them;
  - preserve the remote file's ordering and comments where possible.
- When `--keep-local` is passed, skip all interactive prompts and automatically keep local values for every conflicting key. This is equivalent to answering "old" to every prompt. New keys from the remote template are still added; removed keys are still dropped.
- If `--keep-local` is not passed and a TTY is available, prompt the user to choose between keeping all local values for conflicts or resolving them interactively. If the user chooses to keep all local values, behave as if `--keep-local` were passed; otherwise, proceed with interactive conflict resolution.
- A non-interactive merge (no TTY) must keep existing local values for conflicts, behaving as if `--keep-local` were passed.
- Cross-file decision memory: when multiple `.env` files contain the same conflicting variable, the user's choice for the first occurrence is reused for all subsequent occurrences without prompting again. Decisions are accumulated in a temporary file passed to each merge invocation.
- A remote-added env file is accepted as-is; a remotely removed env file is not recreated.
- `--dry-run` may fetch and inspect but must not reset or write repository files.
- `--force` and `--dry-run` may be combined; `--keep-local` and `--dry-run` may be combined.
- Never commit, push, alter Docker containers, or modify files outside the target repository.
- Clean temporary snapshots and helper scripts on exit, including failure paths.
