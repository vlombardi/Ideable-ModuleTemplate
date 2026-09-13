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

`deny` as the non-TTY default is deliberate: a run with nobody watching must not grant a permission
nobody allowed. The policy governs PERMISSIONS only. A QUESTION is never governed by it, because a
question is a decision the maintainer owes and a policy cannot take it for them.

A QUESTION WAITS FOR THE PERSON, AND BLOCKS THE PLAN RATHER THAN BEING LOST. A prompt sounds the
terminal's bell, offers `I'll answer later` beside the answers, and counts down
(`DEV_CYCLE_ASK_TIMEOUT` seconds, default 120; `0` waits indefinitely). The first keystroke cancels
the countdown for good — someone who has started typing is demonstrably there, and a timer that kept
running would cut a long answer off mid-thought. Someone who is NOT there is not waited on forever:
choosing `I'll answer later`, letting the countdown run out, and having no terminal at all take one
exit — the question is handed back to the router, which records `Blocked` in the plan with the node
to resume at and the question itself. With no terminal the same code goes straight there without
reading stdin, so the agent-driven case is the degenerate case of one mechanism, not a second one.

The countdown reads the terminal a character at a time (cbreak mode), and that mode is restored on
EVERY exit path — a normal answer, the countdown running out, Ctrl-C, and SIGTERM/SIGHUP — because
the failure it risks is leaving the maintainer's shell unusable after the router exits.

ONE AGENT PER SUB-SET, NOT PER NODE. `run_agent` takes a session to `resume` and reports the one it
ran, so the router can hand the next node of the same sub-set back to the agent that performed the
last — `Documenting` and `Committing` judging the diff `Implementing` just wrote, without rebuilding
what it means. `DEV_CYCLE_AGENT_SESSION` sets how long a session lives (`per-sub-set`, `per-plan`,
`per-node`); the router owns WHICH session belongs to what, because that is a fact about the plan.

THE SDK IS OPTIONAL. `import` happens inside `run_agent`, and its absence is a reason the caller
falls back to suggesting the skill — the same shape as a missing CLI. The dev-cycle works with no
agent at all (`--deterministic`), so a hard dependency here would make an optional feature
mandatory.
"""
from __future__ import annotations

import contextlib
import io
import math
import os
import select
import signal
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: How a permission request is answered when the allow-list did not settle it.
POLICY_ENV = "DEV_CYCLE_AGENT_PERMISSIONS"
POLICIES = ("ask", "deny", "accept-edits", "skip")

#: How many seconds a prompt waits for a FIRST keystroke before the question is taken as
#: `I'll answer later`. `0` disables the countdown: the prompt waits indefinitely.
COUNTDOWN_ENV = "DEV_CYCLE_ASK_TIMEOUT"
DEFAULT_COUNTDOWN = 120

#: Replies that mean `I'll answer later`, whatever the question. `0` is the number the option is
#: rendered under, beside the real answers.
LATER_REPLIES = frozenset({"0", "l", "later", "i'll answer later", "ill answer later"})

#: How long one agent SESSION lives — the knob that decides whether the node after this one is
#: performed by the SAME agent, resumed, or by a fresh one that rebuilds its context from the plan.
#:
#: `per-sub-set` is the default because it keeps both properties that matter, each where it earns
#: its keep. WITHIN a sub-set the nodes are one piece of work — `Documenting` and `Committing` judge
#: the diff `Implementing` just wrote — so re-deriving it costs a rebuild and buys nothing; measured
#: on this plan, ~30 tool calls and ~45k tokens per node, against a 170 KB plan file. BETWEEN
#: sub-sets the rebuild IS the point: a fresh agent reads only the plan, so anything the previous
#: one believed and did not write down is caught there rather than carried forward as a premise.
#:
#: `per-plan` is one agent for the whole plan — the "plan-traced fast lane" as a setting rather than
#: a third mode, for a plan small enough that fresh eyes buy little. `per-node` is the behaviour
#: before this knob existed and is kept available, because a node that must not inherit a
#: predecessor's beliefs is a real case and deserves a switch rather than a code change.
SESSION_ENV = "DEV_CYCLE_AGENT_SESSION"
SESSION_GRANULARITIES = ("per-sub-set", "per-plan", "per-node")
DEFAULT_SESSION_GRANULARITY = "per-sub-set"

#: Signals on whose arrival the terminal is restored before the process dies of them. SIGINT is not
#: listed because Python turns it into KeyboardInterrupt, which the `finally` already handles.
_RESTORE_ON = (signal.SIGTERM, signal.SIGHUP)

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


def resolve_countdown(env=None) -> int:
    """Seconds a prompt waits for a first keystroke: the variable when set, else the default.

    Refused rather than defaulted when it is not a whole number, for the same reason as the policy:
    a misspelt value that silently became 120 would look like the variable being ignored, and one
    that became 0 would make the run wait forever with nothing saying why.
    """
    env = os.environ if env is None else env
    stated = (env.get(COUNTDOWN_ENV) or "").strip()
    if not stated:
        return DEFAULT_COUNTDOWN
    if not stated.isdigit():
        raise ValueError(
            f"{COUNTDOWN_ENV}={stated!r} is not a whole number of seconds (0 disables the "
            f"countdown and waits indefinitely). It is refused rather than defaulted."
        )
    return int(stated)


def resolve_session_granularity(env=None) -> str:
    """How long one agent session lives: the variable when set, else `per-sub-set`.

    Refused rather than defaulted, for the third time and the same reason as the policy and the
    countdown: a misspelt `per-subset` that silently became `per-sub-set` would look like the
    variable working, and one that became `per-node` would quietly restore the behaviour the
    setting exists to leave — a difference nobody would see until the bill.
    """
    env = os.environ if env is None else env
    stated = (env.get(SESSION_ENV) or "").strip().lower()
    if not stated:
        return DEFAULT_SESSION_GRANULARITY
    if stated not in SESSION_GRANULARITIES:
        raise ValueError(
            f"{SESSION_ENV}={stated!r} is not one of {', '.join(SESSION_GRANULARITIES)}. It is "
            f"refused rather than defaulted."
        )
    return stated


def session_id_of(message) -> str | None:
    """The SDK session this message belongs to, from whichever message type carries it.

    Two do, and both are read because they arrive at opposite ends of a run: the `init` system
    message names the session before any work happens, and the result message names it again at the
    end. Taking only the result would lose the id of a run that failed part-way — which is exactly
    the run somebody wants to resume.
    """
    data = getattr(message, "data", None)
    if isinstance(data, dict) and data.get("session_id"):
        return str(data["session_id"])
    sid = getattr(message, "session_id", None)
    return str(sid) if sid else None


# ── The terminal ──────────────────────────────────────────────────────────────────────────────


#: Returned by `Terminal.ask_line` when there is no answer to be had — as opposed to an answer of
#: "no". The two were one value, and "I could not read you" was reported to the agent as "the
#: maintainer declined", which is a lie about who decided.
NO_ANSWER = None


class _Later:
    """The value of a prompt nobody was there for: the countdown ran out, or there is no terminal.

    Distinct from `NO_ANSWER` (the terminal went away mid-read, or the person pressed Ctrl-D) so the
    agent can be told WHY the question is open, and distinct from every string so no real answer can
    be mistaken for it. It is FALSY on purpose: every caller that already asks `if not reply` treats
    it as "no answer given", which is what it is — a site this module forgot to teach about it fails
    safe, into the branch that hands the question back, rather than into `int(reply)`.
    """

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "LATER"


LATER = _Later()


@contextlib.contextmanager
def _cbreak(fd: int):
    """Character-at-a-time reading, with the terminal restored on EVERY way out.

    `tty.setcbreak` clears ICANON and ECHO, so a process that dies inside it leaves the maintainer's
    shell echoing nothing and delivering keystrokes one at a time — unusable until they think of
    `reset`. Three exits are covered, because each one was reachable: a normal return and any
    exception through `finally`; Ctrl-C, which Python delivers as KeyboardInterrupt, through the same
    `finally`; and SIGTERM/SIGHUP, whose default disposition kills the process WITHOUT unwinding, so a
    handler restores the mode first and then re-raises the signal with the default disposition — the
    process still dies of the signal it was sent, and says so to its parent.

    The handlers are installed only where Python allows (the main thread) and the previous ones are
    put back afterwards, so a caller's own handling of those signals survives one prompt.

    `TCSANOW` on both the way in and the way out, never `TCSAFLUSH`/`TCSADRAIN`: those wait for
    pending OUTPUT to be transmitted first, and on a terminal nobody is reading — a pty whose master
    has stopped draining, a frozen emulator — that wait is forever. Measured: `tty.setcbreak`'s
    default `TCSAFLUSH` hung the read on a pseudo-terminal before the first byte was ever asked for.
    Only input flags change here, so there is no output for the mode switch to corrupt.
    """
    saved = termios.tcgetattr(fd)

    def restore() -> None:
        with contextlib.suppress(termios.error, OSError):
            termios.tcsetattr(fd, termios.TCSANOW, saved)

    def on_signal(signum, frame):  # noqa: ARG001 — signal-handler contract
        restore()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    previous: dict = {}
    for sig in _RESTORE_ON:
        with contextlib.suppress(ValueError, OSError):  # not the main thread, or not supported
            previous[sig] = signal.signal(sig, on_signal)
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        yield
    finally:
        restore()
        for sig, handler in previous.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, handler)


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

    AND IT NEVER FALLS BACK TO STDIN. A process with no controlling terminal has nobody to ask:
    reading fd 0 there either hits EOF at once or — on a pipe the parent holds open, which is what an
    agent's shell tool gives its children — waits forever. `ask_line` answers `LATER` immediately
    instead, and the router blocks the plan with the question recorded.

    `tty_path` and `countdown_seconds` are injectable so a test can drive the real read on a
    pseudo-terminal with a short countdown; the defaults are the production ones.
    """

    tty_path: str = "/dev/tty"
    countdown_seconds: int | None = None

    def __post_init__(self) -> None:
        self._tty = None
        try:
            # A raw fd wrapped for text, NOT `open(path, "r+")`: that builds a BufferedRandom, which
            # insists the stream be seekable, and a terminal is not — measured on a pty slave, where
            # it refuses with "File or stream is not seekable". `write_through` so a prompt reaches
            # the person the moment it is written, and `O_NOCTTY` so opening a terminal never makes
            # it this process's controlling one.
            fd = os.open(self.tty_path, os.O_RDWR | os.O_NOCTTY)
            self._tty = io.TextIOWrapper(io.FileIO(fd, "r+", closefd=True), encoding="utf-8",
                                         write_through=True)  # held for the run, closed by exit
        except OSError:
            self._tty = None
        if self.countdown_seconds is None:
            self.countdown_seconds = resolve_countdown()

    @property
    def interactive(self) -> bool:
        """Whether there is a person to reach at all."""
        return self._tty is not None

    def write(self, line: str) -> None:
        if self._tty is not None:
            print(line, file=self._tty, flush=True)
        print(line, flush=True)

    def ask_line(self, prompt: str):
        """One line from the person; `LATER` when nobody is there; `NO_ANSWER` when the read failed.

        The bell rings before the prompt, because the person may be looking elsewhere — a node runs
        for twenty minutes without needing them and then needs them at once. Then the countdown
        (`countdown_seconds`; `0` means wait indefinitely, with the terminal's own line editing).

        Neither `LATER` nor `NO_ANSWER` is "no". A run whose terminal has gone away, or whose
        countdown ran out, has not declined anything, and the caller says so rather than attributing
        a decision to the maintainer.
        """
        if self._tty is None:
            return LATER
        try:
            if not self.countdown_seconds:
                print("\a" + prompt, end="", file=self._tty, flush=True)
                line = self._tty.readline()
                if line == "":
                    return NO_ANSWER
                return line.strip()
            print("\a" + prompt.rstrip(), file=self._tty, flush=True)
            return self._read_with_countdown(self.countdown_seconds)
        except (EOFError, KeyboardInterrupt, OSError):
            self.write("")
            return NO_ANSWER

    # -- the countdown read -------------------------------------------------------------------

    def _read_with_countdown(self, seconds: int):
        """Wait for a first keystroke, counting down; then take the line with no clock on it."""
        fd = self._tty.fileno()
        deadline = time.monotonic() + seconds
        shown = 0
        with _cbreak(fd):
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    self._erase(shown)
                    self.write(f"{_ASK_PREFIX}   ⏳ no keystroke in {seconds}s — taken as "
                               f"“I'll answer later”")
                    return LATER
                shown = self._show(
                    f"\r{_ASK_PREFIX}   ⏳ {math.ceil(left):>3}s — any key keeps this prompt open; "
                    f"when it runs out, you answer later ", shown)
                ready, _, _ = select.select([fd], [], [], min(1.0, left))
                if ready:
                    break
            # CANCELLED FOR GOOD. Someone who has started typing is demonstrably there, so from here
            # on there is no clock: a timer that kept running would cut a long answer off.
            self._erase(shown)
            os.write(fd, b"> ")
            return self._edit_line(fd)

    def _show(self, line: str, shown: int) -> int:
        """Redraw the countdown line in place, blanking whatever a longer previous one left."""
        padded = line + " " * max(0, shown - len(line))
        self._tty.write(padded)
        self._tty.flush()
        return len(line)

    def _erase(self, shown: int) -> None:
        if shown:
            self._tty.write("\r" + " " * shown + "\r")
            self._tty.flush()

    def _edit_line(self, fd: int) -> str:
        """A line typed one character at a time, echoed by us because cbreak mode echoes nothing.

        Enough editing to answer a question — backspace, Ctrl-U to clear — and no more. An escape
        sequence (an arrow key) is swallowed rather than typed into the answer; Ctrl-D on an empty
        line is the end of input, exactly as the shell reads it.
        """
        buf = bytearray()
        while True:
            ch = os.read(fd, 1)
            if not ch:
                raise EOFError
            if ch in (b"\r", b"\n"):
                os.write(fd, b"\r\n")
                return buf.decode("utf-8", "replace").strip()
            if ch in (b"\x7f", b"\x08"):
                if buf:
                    while buf and (buf[-1] & 0xC0) == 0x80:  # a multi-byte character's tail…
                        buf.pop()
                    buf.pop()  # …and then its lead byte (or the whole of an ASCII one)
                    os.write(fd, b"\b \b")
                continue
            if ch == b"\x04":
                if not buf:
                    raise EOFError
                continue
            if ch == b"\x15":
                os.write(fd, b"\b \b" * len(buf.decode("utf-8", "replace")))
                buf.clear()
                continue
            if ch == b"\x1b":
                self._swallow_escape_sequence(fd)
                continue
            if ch < b" ":
                continue
            buf += ch
            os.write(fd, ch)

    @staticmethod
    def _swallow_escape_sequence(fd: int) -> None:
        """Discard ONE escape sequence — `ESC [ … final` or `ESC O final` — and nothing after it.

        Not "drain whatever is readable": a pasted line arrives all at once, so that would eat the
        answer typed after an arrow key and then wait for a newline that was already consumed.
        Measured: `a ESC [ A b ⏎` hung the read. A CSI sequence ends at its first byte in
        0x40–0x7E, which is the rule this follows; a lone ESC (nothing within 50ms) is dropped alone.
        """
        if not select.select([fd], [], [], 0.05)[0]:
            return
        introducer = os.read(fd, 1)
        if introducer not in (b"[", b"O"):
            return
        while True:
            byte = os.read(fd, 1)
            if not byte or 0x40 <= byte[0] <= 0x7E:
                return


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
    # Beside the answers, under the one number no option is rendered as. Choosing it is not a
    # decision about the question; it is a decision about WHEN, and the plan records the question.
    terminal.write(f"{_ASK_PREFIX}     0. I'll answer later — the plan is recorded Blocked with "
                   f"this question; answer it on the plan's **Answer**: line, or at the next run")


def _is_an_answer(reply) -> bool:
    """A real reply: a string, not blank, and not one of the ways of saying `later`."""
    return isinstance(reply, str) and bool(reply.strip()) \
        and reply.strip().lower() not in LATER_REPLIES


def _why_open(reply, terminal) -> str:
    """Tell the agent WHY the question is open, in words that name who did what — and who did not."""
    if reply is LATER and not getattr(terminal, "interactive", True):
        return "the question was not answered — this run has no terminal to put it to."
    if reply is LATER:
        return "the question was not answered — the countdown ran out with nobody at the terminal."
    if isinstance(reply, str) and reply.strip():
        return "the maintainer chose to answer this question later."
    return "the question was not answered — the terminal gave no answer, or the person declined."


def _prompt_for(question: dict, index: int, total: int) -> str:
    """The prompt says which question it is collecting, so an answer cannot land on another."""
    if total == 1:
        return f"{_ASK_PREFIX} your answer (number, or your own words): "
    header = (question.get("header") or "").strip()
    return (f"{_ASK_PREFIX} your answer to question {index} of {total}"
            + (f" ({header})" if header else "")
            + " (number, or your own words): ")


def _hand_back_open(unanswered, questions: list, answers: dict) -> None:
    """Give the ROUTER the questions that were put, so an unanswered one is not lost.

    Before this, "no terminal to answer it" produced a denial and nothing else: the agent was told
    the question was open, it said so in a report nobody parsed, and the run carried on to the next
    node with the decision still owed. Three consecutive nodes of the plan that added this recorded
    exactly that, and each time the question survived only because an agent happened to type it
    into the plan by hand.

    The whole set is handed back, answered entries included. A set is denied as a unit (see the
    caller), so an answer already given would otherwise be thrown away too — and the router writes
    every entry into the plan, which is what lets the next `run` re-put only what is still open.

    `unanswered` is an out-parameter rather than a return value because the return value belongs to
    the SDK: this function's result IS the tool's result, and the caller is the permission callback.
    """
    if unanswered is None:
        return
    for question in questions:
        text = question.get("question", "")
        unanswered.append({
            "question": text,
            "header": (question.get("header") or "").strip(),
            "options": [
                {"label": (o.get("label") or "").strip(),
                 "description": (o.get("description") or "").strip()}
                for o in (question.get("options") or [])
            ],
            "answer": answers.get(text),
        })


def answer_question(tool_input: dict, terminal: Terminal, allow, deny, unanswered=None):
    """Put the agent's question to the person and hand the answer back as the tool's result.

    A number picks an option; anything else is taken verbatim, because the honest answer to "which
    of these?" is often "neither, do X". Refusing free text would push the maintainer into the
    closest wrong option, which is worse than a slow answer.

    A set of questions is answered ONE AT A TIME: each is shown immediately before its own labelled
    prompt. There is no syntax for answering several at once, and deliberately so — parsing
    `question 1: 3; question 2: …` means guessing where one answer ends and the next begins, and a
    wrong guess files an answer under a question nobody was looking at.

    FOUR WAYS OF NOT ANSWERING TAKE ONE EXIT: `I'll answer later` (option 0), a countdown that ran
    out, a terminal that is not there at all, and a read that failed (EOF, an empty line). Each is
    a DENIAL carrying that fact, not a default choice — the agent then knows the question is
    unanswered and says so in its report instead of proceeding on a guess nobody made — AND the
    question is handed to the router through `unanswered`, which records `Blocked` in the plan with
    the question and the node to resume at. The denial alone lost it. The denial's wording differs
    by cause, because "the maintainer chose to answer later" and "nobody was there" are different
    facts about who decided what.
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
        if not _is_an_answer(reply):
            _hand_back_open(unanswered, questions, answers)
            return deny(
                _why_open(reply, terminal) + " Do not choose for them: report the question as "
                "open. The router has recorded it in the plan and will block there, so it is not "
                "lost."
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
        if reply is LATER:
            # A permission is not a decision the maintainer owes, so "later" is not an option here
            # and nothing is blocked on it: the countdown running out, or no terminal at all, is
            # reported as exactly that. See `make_can_use_tool` for why the two differ.
            return deny(
                f"{name} was neither allowed nor declined: nobody answered at the terminal before "
                f"the countdown ran out, or this run has no terminal. Nobody decided this. Report "
                f"it as not done, and say that the question went unanswered."
            )
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
            reason = reason if isinstance(reason, str) else ""
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


def make_can_use_tool(policy: str, terminal: Terminal | None = None, unanswered=None):
    """Build the SDK's `can_use_tool` callback for this run.

    One callback, two jobs, because the SDK delivers both through it: a question arrives as the
    `AskUserQuestion` tool, and everything else is a permission request.

    `unanswered` collects the questions that went unanswered, for the router to block the plan on.
    It is passed ONLY to `answer_question`, and deliberately not to `decide_permission`: a refused
    permission is a thing the run could not do, which the agent reports, while an unanswered
    question is a DECISION the maintainer still owes. Blocking a plan on every unsettled `Bash`
    would make the state meaningless.
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
                return answer_question(tool_input, term, allow, deny, unanswered)
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
              label: str | None = None, unanswered=None, resume: str | None = None,
              session: dict | None = None) -> tuple[bool, str | None]:
    """Perform one node by running the agent, answering it as it goes.

    Returns `(ok, reason_if_not)` — the same shape the caller already handles, so an unavailable SDK
    is a fallback reason rather than a crash. A question the person did not answer is NOT a failure
    and does not appear in that tuple: the agent may well have finished everything else. It arrives
    in `unanswered` instead, and the router decides what a plan owing a decision should say.

    `resume` CONTINUES A SESSION rather than starting one, so the node after this one is performed
    by the agent that did the last — which for the nodes of a single sub-set is the same piece of
    work being judged by the mind that wrote it. `session` is a dict the id is written into, the
    same out-parameter shape as `unanswered` and for the same reason: the return tuple is a contract
    several callers and tests already read.

    A SESSION THAT CANNOT BE RESUMED STARTS A FRESH ONE, and says so. The id is remembered across
    processes, so it outlives the agent it names — a machine restarted, a store pruned, a plan
    picked up next week. Only a failure to START is retried: a run that reached the model and
    reported failure is a real result, and running it again would pay for the same work twice.

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

    def _options(resume_id: str | None) -> ClaudeAgentOptions:
        # One `**`, not two: the caller's options and the session are merged into a single dict
        # first, so a caller that passes `resume` itself is overridden here rather than crashing on
        # a duplicate keyword — and the router is the one that knows which session belongs to what.
        settings: dict = dict(extra_options or {})
        if resume_id:
            settings["resume"] = resume_id
        return ClaudeAgentOptions(
            cwd=str(cwd),
            can_use_tool=make_can_use_tool(policy, term, unanswered),
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_keep_alive])]},
            **settings,
        )

    async def _drive(resume_id: str | None):
        failed = None
        async for message in query(prompt=_prompt_stream(), options=_options(resume_id)):
            if not quiet:
                render(message, term)
            if session is not None:
                found = session_id_of(message)
                if found:
                    session["id"] = found
            from claude_agent_sdk import ResultMessage
            if isinstance(message, ResultMessage):
                # Recorded outside the `quiet` guard above: `quiet` silences the terminal, and a
                # run whose cost went unrecorded because nobody was watching is the case this log
                # exists for.
                record_agent_run(message, label, cwd)
            if isinstance(message, ResultMessage) and message.is_error:
                failed = message.result or f"the agent ended with {message.subtype}"
        return failed

    if resume:
        term.write(f"{_PREFIX} resuming session {resume} — this node is performed by the agent "
                   f"that did the last one.")
    try:
        failure = asyncio.run(_drive(resume))
    except Exception as exc:  # noqa: BLE001 — every failure is a fallback reason, never a traceback
        if not resume:
            return False, f"the agent run failed: {type(exc).__name__}: {exc}"
        # Said out loud, never silently: the whole point of resuming is that this node inherits the
        # last one's context, so a fresh session is a DIFFERENT run and a reader must know which
        # they got before they read what it did.
        term.write(f"{_PREFIX} session {resume} could not be resumed "
                   f"({type(exc).__name__}: {exc}) — starting a fresh one.")
        try:
            failure = asyncio.run(_drive(None))
        except Exception as exc:  # noqa: BLE001 — same contract: a reason, not a traceback
            return False, f"the agent run failed: {type(exc).__name__}: {exc}"
    if failure:
        return False, f"the agent reported failure: {failure}"
    return True, None
