#!/usr/bin/env python3
"""The router's side of a conversation with the agent it runs: permissions, and questions.

`scripts/dev/common/dev_cycle.py` performs an LLM node by running an agent. That agent needs two things
from the person at the terminal, and until now it could get neither:

- **permission** for an action the project's allow-list does not already settle;
- **an answer** to a question only the maintainer can decide (`AskUserQuestion` — the mechanical
  form of `rules/general-guidelines.md` § *Decision Making Authority*).

Driven as `claude -p`, it got no channel to either. A tool call outside the allow-list was refused
and a question had nobody to ask, so the `Documenting` node of the framework-version plan ended
twice with "three edits were refused by the permission layer" and a docs gate that never ran. The
remedies the router offered were all policies — `--permission-mode acceptEdits`,
`--dangerously-skip-permissions`, a wider allow-list — which decide before the question is known.

So the router runs the agent through the **Agent SDK** and supplies `can_use_tool`. Both kinds of
request arrive there, and both are answered by the person who ran the command.

WHAT THIS MODULE IS, PRECISELY. The callback and the policy, and nothing else: no plan, no graph, no
git. `dev_cycle.py` owns those and calls `run_agent()`. Keeping them apart is what lets the callback
be tested with a scripted terminal and no agent at all.

THE POLICY, because an unattended run must still be possible. `DEV_CYCLE_AGENT_PERMISSIONS`:

    ask            prompt the terminal (the default when stdin is a TTY)
    deny           refuse anything the allow-list did not settle, and say so
                   (the default when stdin is NOT a TTY — CI, cron, a piped run)
    accept-edits   allow file edits without prompting; still ask for anything else
    skip           allow everything, printed loudly — for an untrusted workspace

`deny` as the non-TTY default is deliberate: it is exactly today's behaviour, now named. A run with
nobody watching must not block on a question, and must not grant one either.

THE SDK IS OPTIONAL. `import` happens inside `run_agent`, and its absence is a reason the caller
falls back to suggesting the skill — the same shape as a missing CLI. The dev-cycle works with no
agent at all (`--deterministic`), so a hard dependency here would make an optional feature
mandatory.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: How a permission request is answered when the allow-list did not settle it.
POLICY_ENV = "DEV_CYCLE_AGENT_PERMISSIONS"
POLICIES = ("ask", "deny", "accept-edits", "skip")

#: Tools whose only effect is to write files — what `accept-edits` covers.
_EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})

#: The tool through which an agent asks the maintainer a question.
QUESTION_TOOL = "AskUserQuestion"

#: How many times an unrecognised reply is asked again before the request is abandoned. Bounded so
#: a terminal that answers nothing useful cannot hang the run forever.
_ASK_ATTEMPTS = 3

_PREFIX = "[agent]"
_ASK_PREFIX = "[dev-cycle ask]"


def resolve_policy(env=None, isatty=None) -> str:
    """The policy for this run: the variable when set, else `ask` on a TTY and `deny` without one.

    Both inputs are injectable so the contract test needs neither a terminal nor an environment.
    """
    env = os.environ if env is None else env
    stated = (env.get(POLICY_ENV) or "").strip().lower()
    if stated:
        if stated not in POLICIES:
            raise ValueError(
                f"{POLICY_ENV}={stated!r} is not one of {', '.join(POLICIES)}. It is refused rather "
                f"than defaulted: a misspelt policy that silently became `deny` would look like the "
                f"agent refusing its own work, and a misspelt one that became `skip` would grant "
                f"everything."
            )
        return stated
    interactive = sys.stdin.isatty() if isatty is None else isatty()
    return "ask" if interactive else "deny"


# ── The terminal ──────────────────────────────────────────────────────────────────────────────


#: Returned by `Terminal.ask_line` when there is no answer to be had — as opposed to an answer of
#: "no". The two were one value, and "I could not read you" was reported to the agent as "the
#: maintainer declined", which is a lie about who decided.
NO_ANSWER = None


@dataclass
class Terminal:
    """Reading from and writing to the person who ran the router.

    A seam, not an abstraction for its own sake: the tests drive the whole callback by scripting
    replies, so every branch below is exercised without a terminal and without an agent.

    IT TALKS TO `/dev/tty`, NOT TO `sys.stdin`. A prompt has to reach the person and their answer has
    to come back whatever else is happening to this process's standard streams — a piped run, a
    redirected log, a library that read a line and left the newline behind. This is what `git`,
    `ssh` and `sudo` do for the same reason, and it is why the answer to "allow?" can no longer be
    lost to whatever else is holding fd 0.
    """

    def __post_init__(self) -> None:
        self._tty = None
        try:
            self._tty = open("/dev/tty", "r+")  # noqa: SIM115 — held for the run, closed by exit
        except OSError:
            self._tty = None

    def write(self, line: str) -> None:
        if self._tty is not None:
            print(line, file=self._tty, flush=True)
        print(line, flush=True)

    def ask_line(self, prompt: str):
        """One line from the person, or `NO_ANSWER` when there is nobody to read.

        `NO_ANSWER` is not "no". A run whose terminal has gone away has not declined anything, and
        the caller says so rather than attributing a decision to the maintainer.
        """
        try:
            if self._tty is not None:
                print(prompt, end="", file=self._tty, flush=True)
                line = self._tty.readline()
                if line == "":
                    return NO_ANSWER
                return line.strip()
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt, OSError):
            self.write("")
            return NO_ANSWER


def describe_tool(name: str, tool_input: dict) -> str:
    """One line naming what the agent is about to do, in its own terms.

    The words the agent used, not a paraphrase: a prompt that summarises loses exactly the detail a
    person needs to decide (which file, which command).
    """
    for key in ("file_path", "path", "command", "pattern", "url", "notebook_path"):
        value = tool_input.get(key)
        if value:
            text = str(value).replace("\n", " ")
            return f"{name} {text[:300]}"
    if not tool_input:
        return name
    key = next(iter(tool_input))
    return f"{name} {key}={str(tool_input[key])[:200]}"


# ── The two conversations ─────────────────────────────────────────────────────────────────────


def _render_question(question: dict, index: int, total: int, terminal: Terminal) -> None:
    """Show ONE question, immediately before its own prompt.

    Every question used to be printed first and the prompts asked afterwards, one per question, all
    reading `your answer (number, or your own words):`. Measured on 2026-09-08 with two questions:
    the maintainer saw both, was given what looked like one prompt for both, and answered
    `question 1: 3; question 2: <text>`. That whole line became question 1's answer — free text,
    since only a bare digit picks an option — and the router then asked question 2 with the same
    unlabelled prompt. Nothing was lost and nothing was misparsed, because nothing ever tried to
    parse it: there is one prompt per question and no combined-answer syntax.

    So a question is not shown until it is the question being asked, and the prompt names which one
    it is. The counter is printed for every question of a set, the last included — it used to be
    omitted there (`if index < len(questions)`), so the final question carried no marker at all and
    read as a continuation of the one above it.
    """
    header = (question.get("header") or "").strip()
    where = f" (question {index} of {total})" if total > 1 else ""
    terminal.write("")
    terminal.write(f"{_ASK_PREFIX} the agent is asking"
                   + (f" about {header}" if header else "") + f"{where}:")
    terminal.write(f"{_ASK_PREFIX}   {question.get('question', '(no question text)')}")
    for choice, option in enumerate(question.get("options") or [], start=1):
        label = option.get("label", "?")
        detail = (option.get("description") or "").strip()
        terminal.write(f"{_ASK_PREFIX}     {choice}. {label}" + (f" — {detail}" if detail else ""))


def _prompt_for(question: dict, index: int, total: int) -> str:
    """The prompt says which question it is collecting, so an answer cannot land on another."""
    if total == 1:
        return f"{_ASK_PREFIX} your answer (number, or your own words): "
    header = (question.get("header") or "").strip()
    return (f"{_ASK_PREFIX} your answer to question {index} of {total}"
            + (f" ({header})" if header else "")
            + " (number, or your own words): ")


def answer_question(tool_input: dict, terminal: Terminal, allow, deny):
    """Put the agent's question to the person and hand the answer back as the tool's result.

    A number picks an option; anything else is taken verbatim, because the honest answer to "which
    of these?" is often "neither, do X". Refusing free text would push the maintainer into the
    closest wrong option, which is worse than a slow answer.

    A set of questions is answered ONE AT A TIME: each is shown immediately before its own labelled
    prompt. There is no syntax for answering several at once, and deliberately so — parsing
    `question 1: 3; question 2: …` means guessing where one answer ends and the next begins, and a
    wrong guess files an answer under a question nobody was looking at.

    No answer (EOF, or an empty line) is a DENIAL carrying that fact, not a default choice. The
    agent then knows the question is unanswered and can say so in its report instead of proceeding
    on a guess nobody made.
    """
    questions = tool_input.get("questions") or []
    if not questions:
        return deny("the agent asked a question with no content, so there is nothing to answer")

    answers: dict[str, str] = {}
    total = len(questions)
    for index, question in enumerate(questions, start=1):
        # Rendered here, not all up front: see `_render_question` for what showing them together
        # cost. One question is on screen at a time, and the prompt below names it.
        _render_question(question, index, total, terminal)
        text = question.get("question", "")
        options = question.get("options") or []
        reply = terminal.ask_line(_prompt_for(question, index, total))
        if reply is NO_ANSWER or not reply:
            return deny(
                "the question was not answered — the run has no terminal to answer it, or the "
                "person declined. Do not choose for them: report the question as open."
            )
        if reply.isdigit() and 1 <= int(reply) <= len(options):
            answers[text] = options[int(reply) - 1].get("label", reply)
        else:
            answers[text] = reply
        terminal.write(f"{_ASK_PREFIX}   recorded: {answers[text]}")
    return allow({"questions": questions, "answers": answers})


def decide_permission(name: str, tool_input: dict, policy: str, terminal: Terminal,
                      always: set, allow, deny):
    """Answer one permission request, per the policy.

    `always` is this run's memory of `a` answers — per tool name, so allowing one `Bash` does not
    silently allow every later `Edit`. It lives for the run and is never persisted: a decision made
    about today's work is not a standing grant, and `.claude/settings.json` is where a standing one
    belongs.
    """
    if policy == "skip":
        return allow(tool_input)
    if policy == "accept-edits" and name in _EDIT_TOOLS:
        return allow(tool_input)
    if name in always:
        return allow(tool_input)
    # `deny` is the only policy that refuses without asking. `accept-edits` covers writes and then
    # ASKS about everything else — it is a shortcut through the common case, not a narrower `deny`.
    # Written the other way round first (`if policy != "ask"`), which silently turned
    # `accept-edits` into "edits only, refuse the rest" and would have refused every Bash call in a
    # run the maintainer thought they were making more permissive.
    if policy == "deny":
        return deny(
            f"{name} is not permitted in this run ({POLICY_ENV}={policy}). Nobody is at the "
            f"terminal to allow it. Report what you could not do rather than working around it."
        )

    terminal.write("")
    terminal.write(f"{_ASK_PREFIX} the agent wants to: {describe_tool(name, tool_input)}")

    # Anything unrecognised is ASKED AGAIN rather than read as "no". Silently turning a stray
    # keystroke, a blank line or a lost answer into a denial is what made `a` — a plain yes —
    # come back to the agent as "the maintainer declined Bash, without giving a reason".
    for attempt in range(_ASK_ATTEMPTS):
        reply = terminal.ask_line(f"{_ASK_PREFIX} allow? [y]es / [n]o / [a]lways this tool: ")
        if reply is NO_ANSWER:
            return deny(
                f"{name} was neither allowed nor declined: the router could not read an answer from "
                f"the terminal. Nobody decided this. Report it as not done, and say that the "
                f"question went unanswered."
            )
        reply = reply.lower()
        if reply in ("y", "yes"):
            return allow(tool_input)
        if reply in ("a", "always"):
            always.add(name)
            terminal.write(f"{_ASK_PREFIX}   {name} allowed for the rest of this run")
            return allow(tool_input)
        if reply in ("n", "no"):
            reason = terminal.ask_line(f"{_ASK_PREFIX} reason for the agent (optional): ")
            reason = "" if reason is NO_ANSWER else reason
            return deny(
                (f"the maintainer declined {name}: {reason}" if reason
                 else f"the maintainer declined {name}, without giving a reason")
                + ". Do not attempt it another way; report it as not done."
            )
        remaining = _ASK_ATTEMPTS - attempt - 1
        terminal.write(f"{_ASK_PREFIX}   {reply!r} is not one of y / n / a"
                       + (f" — {remaining} more tr{'y' if remaining == 1 else 'ies'}" if remaining
                          else ""))
    return deny(
        f"{name} was neither allowed nor declined: {_ASK_ATTEMPTS} answers were given and none was "
        f"y, n or a. Nobody decided this. Report it as not done."
    )


def make_can_use_tool(policy: str, terminal: Terminal | None = None):
    """Build the SDK's `can_use_tool` callback for this run.

    One callback, two jobs, because the SDK delivers both through it: a question arrives as the
    `AskUserQuestion` tool, and everything else is a permission request.
    """
    import asyncio

    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    term = terminal or Terminal()
    always: set[str] = set()
    # ONE CONVERSATION AT A TIME. `can_use_tool` is async and the SDK may invoke it concurrently for
    # tool calls it issues in parallel. Two callbacks prompting the same terminal interleave their
    # questions and race for the next line typed, so an answer can be delivered to a question the
    # person was not looking at — which is one explanation for a plain `a` arriving as a decline.
    turn = asyncio.Lock()

    def allow(updated_input):
        return PermissionResultAllow(updated_input=updated_input)

    def deny(message):
        return PermissionResultDeny(message=message)

    async def can_use_tool(tool_name: str, tool_input: dict, context):  # noqa: ARG001 — SDK contract
        async with turn:
            if tool_name == QUESTION_TOOL:
                return answer_question(tool_input, term, allow, deny)
            return decide_permission(tool_name, tool_input, policy, term, always, allow, deny)

    return can_use_tool


# ── Progress, from the SDK's own messages ─────────────────────────────────────────────────────


def render(message, terminal: Terminal) -> None:
    """Print what the agent is doing. Typed messages, so nothing is parsed out of a byte stream."""
    from claude_agent_sdk import (AssistantMessage, ResultMessage, SystemMessage, TextBlock,
                                  ToolResultBlock, ToolUseBlock, UserMessage)

    if isinstance(message, SystemMessage):
        if message.subtype == "init":
            model = (message.data or {}).get("model", "?")
            terminal.write(f"{_PREFIX} session started · model {model}")
        return
    if isinstance(message, AssistantMessage):
        for block in message.content or []:
            if isinstance(block, TextBlock) and block.text.strip():
                for line in block.text.strip().splitlines():
                    if line.strip():
                        terminal.write(f"{_PREFIX} {line[:200]}")
            elif isinstance(block, ToolUseBlock):
                terminal.write(f"{_PREFIX}   · {describe_tool(block.name, block.input or {})}")
        return
    if isinstance(message, UserMessage):
        for block in message.content or []:
            # Only failures: the call line already said what was attempted, and echoing every
            # result buries the one thing a watcher needs to see.
            if isinstance(block, ToolResultBlock) and block.is_error:
                terminal.write(f"{_PREFIX}   ✗ tool error: {str(block.content)[:200]}")
        return
    if isinstance(message, ResultMessage):
        seconds = (message.duration_ms or 0) / 1000
        cost = message.total_cost_usd
        cost_part = f" · ${cost:.2f}" if isinstance(cost, (int, float)) else ""
        status = "failed" if message.is_error else "finished"
        terminal.write(f"{_PREFIX} {status} in {seconds:.0f}s · {message.num_turns} turns{cost_part}")


# ── What the run cost, kept ───────────────────────────────────────────────────────────────────

#: Beside the test history, because it answers the same kind of question and travels the same way:
#: `TEST_REPORTS/` is committed, is already bookkeeping to the pre-push gate, and is not shipped to
#: module projects.
AGENT_RUN_LOG = "TEST_REPORTS/AGENT-RUNS.md"

_AGENT_RUN_HEADER = """# Agent runs

One row per LLM node the router performed through the Agent SDK. Appended by
`scripts/dev/common/agent_conversation.py` as each run ends.

**Why this file exists.** The duration was printed to the terminal and kept nowhere, so "are the
agent steps getting slower?" had no answer — asked on 2026-09-09, it could only be answered for the
*test suite*, whose history `TEST_REPORTS/` had all along. A number nobody records is a number
nobody can compare.

`s/turn` is the useful column for that question: total seconds move with how much work a node was
given, while seconds per turn is closer to how fast the model itself was answering.

| Finished | Node / skill | Seconds | Turns | s/turn | Cost | Result | Commit |
|:--|:--|--:|--:|--:|--:|:--|:--|
"""


def record_agent_run(message, label: str | None, cwd) -> None:
    """Append one row for a finished agent run. Never raises: a log is not worth failing a node."""
    with contextlib.suppress(Exception):
        turns = message.num_turns or 0
        seconds = (message.duration_ms or 0) / 1000
        per_turn = f"{seconds / turns:.1f}" if turns else "—"
        cost = message.total_cost_usd
        cost_cell = f"${cost:.2f}" if isinstance(cost, (int, float)) else "—"
        commit = "—"
        with contextlib.suppress(Exception):  # an unknown commit is a cell, not a failure
            done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(cwd),
                                  capture_output=True, text=True, timeout=10)
            if done.returncode == 0:
                commit = done.stdout.strip() or "—"
        path = Path(cwd) / AGENT_RUN_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(_AGENT_RUN_HEADER, encoding="utf-8")
        row = (f"| {datetime.now():%Y-%m-%d %H:%M} | {label or '—'} | {seconds:.0f} | {turns} | "
               f"{per_turn} | {cost_cell} | {'failed' if message.is_error else 'ok'} | {commit} |\n")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(row)


# ── Running one node's skill ──────────────────────────────────────────────────────────────────


def run_agent(prompt: str, cwd, policy: str, extra_options: dict | None = None,
              terminal: Terminal | None = None, quiet: bool = False,
              label: str | None = None) -> tuple[bool, str | None]:
    """Perform one node by running the agent, answering it as it goes.

    Returns `(ok, reason_if_not)` — the same shape the caller already handles, so an unavailable SDK
    is a fallback reason rather than a crash.

    `quiet` silences the PROGRESS rendering and nothing else. A prompt is never silenced: a run
    that hid the question it is blocked on would look like a hang, which is worse than noise.

    THE STREAMING PROMPT AND THE KEEP-ALIVE HOOK ARE NOT DECORATION. In Python the SDK invokes
    `can_use_tool` only while the input stream is open; with a plain string prompt it closes the
    stream after the last message and the callback never fires — the permission request would be
    settled without anyone being asked, which is the exact defect this module exists to remove. A
    registered hook keeps it open. This is documented SDK behaviour, not a workaround of ours.
    """
    try:
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
    except ImportError as exc:
        # NAMING THE INTERPRETER is the whole message. The router runs under whatever `python3`
        # resolves to in the caller's shell, which on 2026-09-08 was not the virtualenv the SDK had
        # been installed into — so "not installed" was true and useless, and the obvious next step
        # (`pip install claude-agent-sdk`) would have installed it somewhere else again.
        return False, (
            f"the Claude Agent SDK is not importable by {sys.executable} ({exc}), which is the "
            f"interpreter this router runs under. Install it THERE — "
            f"`{sys.executable} -m pip install claude-agent-sdk` — or drive this node yourself with "
            f"--deterministic"
        )

    import asyncio

    term = terminal or Terminal()

    async def _keep_alive(input_data, tool_use_id, context):  # noqa: ARG001 — SDK contract
        return {}

    async def _prompt_stream():
        yield {"type": "user", "message": {"role": "user", "content": prompt},
               "parent_tool_use_id": None, "session_id": "dev-cycle"}

    options = ClaudeAgentOptions(
        cwd=str(cwd),
        can_use_tool=make_can_use_tool(policy, term),
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_keep_alive])]},
        **(extra_options or {}),
    )

    async def _drive():
        failed = None
        async for message in query(prompt=_prompt_stream(), options=options):
            if not quiet:
                render(message, term)
            from claude_agent_sdk import ResultMessage
            if isinstance(message, ResultMessage):
                # Recorded outside the `quiet` guard above: `quiet` silences the terminal, and a
                # run whose cost went unrecorded because nobody was watching is the case this log
                # exists for.
                record_agent_run(message, label, cwd)
            if isinstance(message, ResultMessage) and message.is_error:
                failed = message.result or f"the agent ended with {message.subtype}"
        return failed

    try:
        failure = asyncio.run(_drive())
    except Exception as exc:  # noqa: BLE001 — every failure is a fallback reason, never a traceback
        return False, f"the agent run failed: {type(exc).__name__}: {exc}"
    if failure:
        return False, f"the agent reported failure: {failure}"
    return True, None
