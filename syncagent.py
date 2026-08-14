#!/usr/bin/env python3
"""
syncagent - a three-agent workspace for Claude Code, Gemini CLI and Codex CLI.

Standard library only. No pip install.

  python syncagent.py init ~/work/my-project --track code
  cd ~/work/my-project
  python syncagent.py start
  python syncagent.py dash

Subcommands
  init    create a workspace folder with all .md files, configs and guardrails
  start   print (or launch) the three CLIs with the right flags
  ask     run gemini or codex headless, log telemetry, write the answer to a file
  ref     link an outside folder in read-only (write access is denied)
  tasks   the roadmap ledger: validate, next, parallel, start, done, block, list
  resume  pick up an interrupted session without re-deriving the plan
  gate    advance the project phase
  status  one-screen text summary
  usage   measured Claude token spend and how much subscription headroom is left
  dash    local web dashboard at http://127.0.0.1:7777
"""

import argparse
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ORCH = ".syncagent"
VERSION = "1.0"


# --------------------------------------------------------------------------
# tracks
# --------------------------------------------------------------------------

TRACKS = {
    "code": {
        "label": "Software project",
        "gates": ["align", "research", "plan", "build", "review", "done"],
        "artifact": "the code in this repository",
        "spec_sections": [
            ("Goal", "One paragraph. What should be true when this is finished?"),
            ("Acceptance criteria", "Numbered, each independently checkable. A test or a command that proves it."),
            ("Non-goals", "Things that are explicitly out of scope. This section prevents scope drift more than any other."),
            ("Constraints", "Language, framework, style, performance, anything that is not negotiable."),
            ("Unknowns", "Anything needing research before code is written. Leave blank if none."),
        ],
        "review_focus": (
            "correctness, edge cases, error handling, security, and whether the diff "
            "actually satisfies every numbered acceptance criterion"
        ),
    },
    "assignment": {
        "label": "Coursework / assignment",
        "gates": ["align", "research", "plan", "draft", "review", "done"],
        "artifact": "the document being written",
        "spec_sections": [
            ("Assignment", "Course, title, due date, word or page count, format."),
            ("Rubric", "Paste the marking rubric verbatim. Each row becomes an acceptance criterion."),
            ("Thesis / position", "The argument in one sentence. If unknown at the start, write UNDECIDED."),
            ("Sources required", "Citation style, minimum sources, allowed source types."),
            ("Non-goals", "What this piece is not arguing. Keeps the draft from sprawling."),
        ],
        "review_focus": (
            "argument structure, whether each rubric row is satisfied, unsupported claims, "
            "citation completeness, and repetition"
        ),
    },
    "resume": {
        "label": "Resume / application tailoring",
        "gates": ["align", "research", "plan", "draft", "review", "done"],
        "artifact": "the tailored resume and cover letter",
        "spec_sections": [
            ("Target role", "Company, title, link to posting."),
            ("Job description", "Paste it in full. Everything downstream keys off this."),
            ("Base resume", "Path to the master resume in .syncagent/refs/ or inputs/."),
            ("Truth constraints", "Every claim must trace to something real. List anything that must NOT be overstated."),
            ("Non-goals", "Roles or skills not to emphasise for this application."),
        ],
        "review_focus": (
            "keyword alignment with the posting, whether every bullet is verifiable against the base "
            "resume, weak verbs, quantification gaps, length, and ATS-hostile formatting"
        ),
    },
    "generic": {
        "label": "General project",
        "gates": ["align", "research", "plan", "build", "review", "done"],
        "artifact": "the deliverable",
        "spec_sections": [
            ("Goal", "One paragraph."),
            ("Acceptance criteria", "Numbered and independently checkable."),
            ("Non-goals", "Explicitly out of scope."),
            ("Constraints", "Non-negotiables."),
            ("Unknowns", "Needs research first."),
        ],
        "review_focus": "correctness, completeness against the acceptance criteria, and unsupported claims",
    },
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_root(start=None):
    """Walk upward looking for a .syncagent directory."""
    p = Path(start or os.getcwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / ORCH).is_dir():
            return candidate
    sys.exit("Not inside a SyncAgent workspace. Run 'syncagent.py init <folder>' first.")


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def have(binary):
    return shutil.which(binary) is not None


def exe(binary):
    """Resolve a CLI to a full path before launching it.

    On Windows the three CLIs are npm shims - `gemini.CMD`, not `gemini.exe`.
    shutil.which() finds them because it honours PATHEXT, but CreateProcess
    only ever appends `.exe` when it searches PATH, so passing the bare name
    to subprocess raises FileNotFoundError on a machine where the CLI is
    plainly installed. Hand it the resolved path instead.
    """
    return shutil.which(binary) or binary


def cli_invocation():
    """How an agent should invoke this tool from inside a generated workspace.

    Baked in at init time rather than written as a literal `python syncagent.py`,
    which is wrong twice over: the workspace is usually not the folder syncagent.py
    lives in, and on macOS `python` frequently does not exist at all - Homebrew and
    python.org both install `python3` only. Resolving the interpreter and the script
    here makes the generated instructions work from any directory, on any platform,
    with no alias or PATH setup.
    """
    py, script = sys.executable or "python3", str(Path(__file__).resolve())
    quote = lambda s: f'"{s}"' if " " in s else s
    return f"{quote(py)} {quote(script)}"


def log_event(root, record):
    record["ts"] = now_iso()
    line = json.dumps(record, ensure_ascii=False)
    with open(root / ORCH / "telemetry.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_telemetry(root):
    path = root / ORCH / "telemetry.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --------------------------------------------------------------------------
# the task ledger - pure functions, no filesystem, so they can be tested alone
# --------------------------------------------------------------------------

TASKS = "TASKS.json"
STATUSES = ("todo", "doing", "done", "blocked")
VALUES = ("high", "medium", "low")
SIZES = ("S", "M", "L")
ASSIGNEES = ("claude", "gemini", "codex")

VALUE_RANK = {"high": 0, "medium": 1, "low": 2}
SIZE_RANK = {"S": 0, "M": 1, "L": 2}
VALUE_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def natural_key(task_id):
    """T2 sorts before T10. Plain string order would not, and the ordering rule
    is supposed to be obvious to a human reading `tasks list`."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(task_id))]


def order_key(task):
    """value desc, then size asc, then id asc - see brief section 4.

    Smaller tasks first among equal value because a small task checkpoints
    sooner, and the point of the whole ordering is that an interrupted run
    leaves behind the work worth having.
    """
    return (VALUE_RANK.get(task.get("value"), 1),
            SIZE_RANK.get(task.get("size"), 1),
            natural_key(task.get("id", "")))


def find_cycle(tasks):
    """Return one dependency cycle as a list of ids, or None."""
    edges = {t.get("id"): [d for d in (t.get("depends_on") or [])] for t in tasks}
    state, stack = {}, []

    def walk(node):
        if state.get(node) == "done":
            return None
        if state.get(node) == "open":
            return stack[stack.index(node):] + [node]
        state[node] = "open"
        stack.append(node)
        for dep in edges.get(node, []):
            if dep in edges:
                found = walk(dep)
                if found:
                    return found
        stack.pop()
        state[node] = "done"
        return None

    for tid in edges:
        found = walk(tid)
        if found:
            return found
    return None


def validate_tasks(doc):
    """Return (errors, warnings). Errors block; warnings are advice."""
    errors, warnings = [], []

    if not isinstance(doc, dict):
        return ["TASKS.json must be a JSON object with a 'tasks' list."], []
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        return ["TASKS.json has no 'tasks' list."], []

    seen = set()
    for i, t in enumerate(tasks):
        where = f"task #{i + 1}"
        if not isinstance(t, dict):
            errors.append(f"{where}: not an object.")
            continue
        tid = t.get("id")
        where = tid or where
        if not tid or not isinstance(tid, str):
            errors.append(f"{where}: missing a string 'id'.")
            continue
        if tid in seen:
            errors.append(f"{tid}: duplicate id. Ids must be unique and are never renumbered.")
        seen.add(tid)

        if not t.get("title"):
            errors.append(f"{tid}: missing 'title'.")
        for field, allowed in (("status", STATUSES), ("value", VALUES),
                               ("size", SIZES), ("assignee", ASSIGNEES)):
            val = t.get(field)
            if val is not None and val not in allowed:
                errors.append(f"{tid}: {field} is {val!r}, expected one of {', '.join(allowed)}.")
        for field in ("files", "depends_on"):
            val = t.get(field)
            if val is not None and (not isinstance(val, list)
                                    or any(not isinstance(x, str) for x in val)):
                errors.append(f"{tid}: '{field}' must be a list of strings.")

        if not t.get("acceptance"):
            warnings.append(f"{tid}: no acceptance criterion named. Usually means the spec "
                            f"is incomplete - say so rather than inventing one.")
        if not (t.get("files") or []):
            warnings.append(f"{tid}: empty 'files'. It will never share a parallel batch.")

    for t in tasks:
        if not isinstance(t, dict):
            continue
        for dep in (t.get("depends_on") or []):
            if isinstance(dep, str) and dep not in seen:
                errors.append(f"{t.get('id')}: depends_on '{dep}', which is not a task id.")

    cycle = find_cycle([t for t in tasks if isinstance(t, dict) and t.get("id")])
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))

    if len(tasks) > 40:
        warnings.append(f"{len(tasks)} tasks. Past ~40 the tasks are usually too small.")

    return errors, warnings


def ready_tasks(tasks):
    """Every todo task whose dependencies are all done, in the order to do them."""
    done = {t.get("id") for t in tasks if t.get("status") == "done"}
    ready = [t for t in tasks
             if t.get("status") == "todo"
             and all(d in done for d in (t.get("depends_on") or []))]
    return sorted(ready, key=order_key)


def parallel_batch(ordered, max_n=3):
    """A batch that is safe to run concurrently: no two tasks touch the same file.

    An empty 'files' list means the footprint is unknown, and an unknown
    footprint conflicts with everything - such a task is returned on its own.
    """
    if max_n < 1:
        return []
    batch, claimed = [], set()
    for t in ordered:
        files = set(t.get("files") or [])
        if not files:
            if not batch:
                return [t]
            continue
        if files & claimed:
            continue
        batch.append(t)
        claimed |= files
        if len(batch) >= max_n:
            break
    return batch


def tasks_summary(tasks):
    """Counts, value-weighted completion, and the ordered ready list."""
    by_status = {s: 0 for s in STATUSES}
    for t in tasks:
        by_status[t.get("status", "todo")] = by_status.get(t.get("status", "todo"), 0) + 1

    earned = sum(VALUE_WEIGHT.get(t.get("value"), 2) for t in tasks if t.get("status") == "done")
    possible = sum(VALUE_WEIGHT.get(t.get("value"), 2) for t in tasks)

    return {
        "total": len(tasks),
        "by_status": by_status,
        "done": by_status.get("done", 0),
        "value_percent": round(100 * earned / possible) if possible else 0,
        "ready": [t.get("id") for t in ready_tasks(tasks)],
        "tasks": tasks,
    }


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def spec_template(track_key, name):
    track = TRACKS[track_key]
    lines = [
        f"# SPEC - {name}",
        "",
        "> STATUS: DRAFT",
        ">",
        "> Nothing gets built until you replace DRAFT with APPROVED on the line above.",
        "> This is the gate that stops all three agents from confidently building the wrong thing.",
        "",
        f"Track: **{track['label']}**",
        "",
    ]
    for heading, hint in track["spec_sections"]:
        lines += [f"## {heading}", "", f"_{hint}_", "", ""]
    return "\n".join(lines)


QUESTIONS_TEMPLATE = """# Open questions

Agents append questions here. You answer them inline, then tick the box.
Anything unticked shows up as PENDING on the dashboard.

Format:

```
- [ ] **(claude)** Question text here?
      **A:**
```

---

"""

STATUS_TEMPLATE = """# Status

_Maintained by Claude. You read it; you don't have to write it._

## Now

Nothing started yet.

## Last cycle

-

## Blocked on

-
"""

DECISIONS_TEMPLATE = """# Decisions

Append-only. Every entry records a disagreement and how it was settled,
so the same argument never happens twice.

Format:

### YYYY-MM-DD - short title
- **Question:**
- **Positions:** claude / gemini / codex
- **Settled by:** (test | your call | evidence)
- **Outcome:**

---

"""


def prompt_files(track_key):
    track = TRACKS[track_key]
    focus = track["review_focus"]
    artifact = track["artifact"]

    align = """You are helping define a task before any work starts.

Read the task description below. Do NOT propose a solution and do NOT start work.

Return ONLY your three most important blocking questions - the ones where guessing
wrong would waste the most effort. Skip anything you could reasonably assume.
One line each, no preamble.

TASK:
{INPUT}
"""

    research = """You are the research agent. Use web search.

Answer the research questions below about the current task.

Hard rules:
- Every factual claim must be followed by a source URL in parentheses. No URL means
  you must not state the claim.
- If you cannot verify something, write "UNVERIFIED:" and say what you would need.
- Prefer official documentation and primary sources over blog posts.
- Be dense. No introductions, no summaries of what you are about to say.

Return markdown with a "## Findings" section and a "## Still unknown" section.

CONTEXT (the frozen spec):
{SPEC}

RESEARCH QUESTIONS:
{INPUT}
"""

    review = f"""You are a reviewer. You did not write this work and you have no stake in it.

Review the change below against the spec. Focus on {focus}.

Hard rules:
- Every finding MUST cite a specific file and line. A finding without a location is
  discarded unread, so do not bother writing it.
- Severity is one of BLOCKER, MAJOR, NIT.
  BLOCKER = violates a stated acceptance criterion, or is outright broken.
  MAJOR   = real problem a careful reviewer would insist on.
  NIT     = style or preference. Use sparingly.
- Do not restate what the change does. Do not praise it.
- If you find nothing above NIT, return an empty findings list. That is a valid,
  useful answer and is better than inventing work.

Return ONLY JSON matching this shape:
{{"findings": [{{"severity": "...", "file": "...", "line": 0,
                 "claim": "...", "evidence": "...", "fix": "..."}}],
  "verdict": "pass" | "revise"}}

SPEC:
{{SPEC}}

CHANGE (this is {artifact}):
{{INPUT}}
"""

    tiebreak = """You are the tiebreaker. Two other reviewers disagree.

Read both positions and the underlying change. Decide which is correct, or say that
neither is and why. Be short - under 200 words. Cite file and line.

If the disagreement can be settled by running something (a test, a command, a check),
say exactly what to run instead of arguing.

SPEC:
{SPEC}

DISAGREEMENT:
{INPUT}
"""

    return {
        "align.md": align,
        "research.md": research,
        "review.md": review,
        "tiebreak.md": tiebreak,
    }


def claude_md(track_key, name, cli):
    track = TRACKS[track_key]
    gates = " -> ".join(track["gates"])
    build = "draft" if "draft" in track["gates"] else "build"
    return f"""# {name}

You are the orchestrator of a three-agent workspace. You do the building. Two other
agents consult, and they run as one-shot subprocesses that hold no context between calls.

## Roles

| Agent  | Job | How it runs |
|--------|-----|-------------|
| Claude (you) | All implementation, all file edits, all orchestration | interactive, this session |
| Gemini | Web research, the primary reviewer, and mechanical build tasks | `{cli} ask gemini --role research\\|review` |
| Codex  | Tiebreaker only, when Gemini and you disagree | `{cli} ask codex --role tiebreak` |

The SyncAgent CLI is invoked as `{cli}` from anywhere in this workspace. That exact
string is correct on this machine; do not substitute `python syncagent.py`, which is
not on the path from here.

Codex is on a free tier with tight limits. Do not call it for routine review. Call it
only when there is a real disagreement, or once at the very end for a final pass.
Every Codex call costs the user something scarce; treat it that way.

## The loop

Phases: {gates}

**align** - Draft `.syncagent/SPEC.md` from what the user asked. Then send the raw task
description (not the whole spec, not the repo) to Gemini with `--role align` and ask for
its blocking questions. Merge its questions with your own into `.syncagent/QUESTIONS.md`,
deduplicated, as unchecked boxes. Then stop and tell the user to answer them.

Do not proceed until `SPEC.md` says `STATUS: APPROVED`. Check it. If it still says
DRAFT, say so and stop. This is not a formality - it is the only thing standing
between the user and three agents efficiently building the wrong thing.

**research** - Only if the spec's Unknowns section is non-empty. Send the questions to
Gemini with `--role research`. Output lands in `.syncagent/RESEARCH.md`. Treat any claim
in it without a URL as if it were not there.

**plan** - Decompose the approved spec into `.syncagent/TASKS.json`. This is the roadmap,
and it lives on disk precisely so that a session which dies at 70% costs one task rather
than the whole plan. Write it, then `{cli} tasks validate`, then stop and have
the user look at the roadmap before anything gets built.

Each task needs: a stable `id` (never renumbered - ids end up in commit messages), a
`title`, the `files` it expects to touch, `depends_on` ids, an `acceptance` string naming
a numbered criterion in SPEC.md, `value`, `size`, and `assignee`.

- `value` is high/medium/low judged by *how useful the project is to the user if it
  stopped right after this task* - not by technical importance. The CLI does the highest
  value first, so this field is what decides whether hitting a usage limit at 60% leaves
  the user with something that works or with 60% of a scaffold.
- `size` is S/M/L, rough. Split an L into two Ms.
- `files` should be your honest best guess. An empty list means "unknown footprint" and
  the task is then never allowed to share a parallel batch.
- If a task cannot name an acceptance criterion, the spec is incomplete. Say so. Do not
  invent one.

Keep it under about 40 tasks. More than that and the tasks are too small to be worth
tracking separately.

**Routing.** The scarce resource is your own quota, not capability in the abstract:
- `claude` (you) - anything where judgment changes the outcome: architecture, data
  models, concurrency, security-sensitive paths, anything spanning more than two modules,
  and the first instance of any new pattern.
- `gemini` - mechanical work against an *already established* pattern: the fifth CRUD
  endpoint once the first exists, test scaffolding, docstrings, config files, plain data
  transforms. Its `notes` must name the file that demonstrates the pattern to copy.
- `codex` - nothing. It stays the tiebreaker.

When unsure, assign yourself. A wrong `gemini` assignment costs a rework cycle, which is
more expensive than the quota it saved.

**{build}** - Work one task at a time, in the order the CLI gives you:

```
{cli} tasks next      # the task to do, as JSON
{cli} tasks start T3
...implement it...
{cli} tasks done T3   # stamps it, commits as "T3: <title>"
```

One task per commit. Do not batch several tasks into one commit - the ids in the history
are what make a resumed session cheap. Keep `.syncagent/STATUS.md` current as you go.

**Parallelism.** Fan out for *investigation*, stay serial for *implementation*. Subagents
are good at "read these four modules and report how auth flows" - isolated context,
read-only, results collapse into a short summary. They are bad at editing concurrently.
If you do want concurrent implementation, `{cli} tasks parallel` returns only
tasks whose `files` sets are provably disjoint; never exceed what it returns.

**review** - Send the spec plus the change to Gemini with `--role review`. It returns
JSON findings.
- Discard any finding with no file/line.
- Only BLOCKER findings force another build pass.
- MAJOR goes on a list for the user to decide.
- NIT is ignored unless the user asks.
- Maximum two review rounds. After the second, escalate to the user regardless of
  what is outstanding. Looping a third time has never once been worth the tokens.

**tiebreak** - If you believe a Gemini finding is wrong and it matters, do not argue in
prose. Either write a test that settles it, or call Codex once with `--role tiebreak`.
Log the outcome in `.syncagent/DECISIONS.md` so it never gets relitigated.

## Resuming

If this session is a continuation, run `{cli} resume` first and start from what
it names. Do not re-read the repository to rebuild the plan - the plan is on disk, and
re-deriving it is the single most expensive thing a resumed session can do.

## Token discipline

- Reviewers get the spec and the diff. Never the repository.
- Before any `ask`, consider whether you could answer it yourself in one thought. If yes,
  do that instead.
- Long agent outputs go to files under `.syncagent/`, not into this conversation.

## Guardrails

- `.syncagent/refs/` is read-only source material. Never write there.
- If the user references a file outside this folder, link it with
  `{cli} ref <path>` rather than reaching for it directly.
- Log every consult with the SyncAgent CLI so it shows up on the dashboard. If you shell
  out to `gemini` or `codex` directly, the telemetry is lost and the dashboard lies.
- Your own token usage is measured for you, straight off this session's transcript. Do
  not estimate it and do not run `log` for it. If the user asks how much is left, run
  `{cli} usage` and read the answer out; the burn rate and the headroom are real numbers.
- If `{cli} usage` reports no transcripts, the run is not being recorded. Say so rather
  than guessing at a figure.
"""


def gemini_md(name):
    return f"""# {name}

You are being called as a consultant into someone else's workspace. You are not
driving this project.

- Read `.syncagent/SPEC.md` for what the project is actually trying to do.
- Answer only what you were asked. No preamble, no summary of your own output.
- Every factual claim needs a source URL. No URL means do not make the claim.
- Never edit files. You are read-only here.
- Being brief is part of the job. Someone is paying for every token.
"""


def agents_md(name):
    return f"""# {name}

You are the tiebreaker for this workspace, called only when two other agents disagree.

- Read `.syncagent/SPEC.md` and `.syncagent/DECISIONS.md` first.
- Be short. Under 200 words unless the question genuinely cannot be settled briefly.
- Cite file and line for anything you assert about the work.
- If the disagreement is empirically testable, say what to run instead of arguing.
- Never edit files. You run read-only.
"""


def claude_settings():
    return {
        "$schema": "https://json.schemastore.org/claude-code-settings.json",
        "permissions": {
            "deny": [
                "Edit(./.syncagent/refs/**)",
                "Write(./.syncagent/refs/**)",
                "Edit(./.syncagent/telemetry.jsonl)",
                "Write(./.syncagent/telemetry.jsonl)",
                "Read(./.env)",
                "Read(./.env.*)",
                "Read(./secrets/**)",
                "Bash(rm -rf /*)",
                "Bash(rm -rf ~*)",
                "Bash(sudo *)",
                "Bash(curl *|*sh)",
                "Bash(git push --force*)",
            ],
            "ask": [
                "Bash(git push*)",
                "Bash(npm publish*)",
                "Bash(gh release*)",
            ],
            "additionalDirectories": [],
        },
    }


def slash_commands(track_key, cli):
    build = "draft" if "draft" in TRACKS[track_key]["gates"] else "build"
    return {
        "align.md": f"""Start the alignment phase for: $ARGUMENTS

1. Draft `.syncagent/SPEC.md` from the request. Fill every section. Where you are
   guessing, mark it clearly rather than smoothing over it.
2. Send the raw request (not the spec) to Gemini:
   `{cli} ask gemini --role align --text "$ARGUMENTS"`
3. Merge Gemini's blocking questions with your own into `.syncagent/QUESTIONS.md`
   as unchecked boxes. Deduplicate aggressively - overlapping questions are the
   normal case, not the exception.
4. Set phase: `{cli} gate align`
5. Stop. Tell the user to answer QUESTIONS.md and set SPEC.md to APPROVED.

Do not write any project code in this command.
""",
        "research.md": f"""Run the research phase.

1. Verify `.syncagent/SPEC.md` says APPROVED. If not, stop and say so.
2. Read the Unknowns section. If empty, skip to plan and say why.
3. `{cli} ask gemini --role research --text "<the unknowns>"`
4. Read `.syncagent/RESEARCH.md`. Strike any claim with no URL.
5. `{cli} gate research`
""",
        "plan.md": f"""Build the roadmap. No implementation in this command.

1. Verify `.syncagent/SPEC.md` says APPROVED. If not, stop and say so.
2. Decompose the spec into `.syncagent/TASKS.json`. Every task needs a stable id, a
   title, its expected `files`, `depends_on` ids, an `acceptance` string naming a
   numbered criterion in SPEC.md, `value`, `size`, and `assignee`.
   - `value` = how useful the project is to the user if it stopped right after this
     task. Not technical importance. This field decides what survives a usage limit.
   - `files` = your honest best guess. Empty means unknown footprint, and unknown
     footprints are never allowed to run concurrently.
   - `assignee` = `claude` for anything needing judgment; `gemini` only for mechanical
     work against a pattern that already exists, with the exemplar named in `notes`.
   - If a task cannot name an acceptance criterion, the spec is incomplete. Say so.
3. `{cli} tasks validate` - fix everything it names.
4. `{cli} gate plan`
5. `{cli} tasks list`, then stop. The user reviews the roadmap before anything is built.
""",
        "resume.md": f"""Pick up an interrupted session.

1. `{cli} resume`
2. Continue from the task it names. If it reset a task from `doing` back to `todo`,
   check `git status` first - that task's partial work may be uncommitted.

Do not re-read the repository to reconstruct the plan, and do not restate the spec.
The roadmap is on disk. Rediscovery is exactly the cost this command exists to avoid.
""",
        f"{build}.md": f"""Run the {build} phase, one task at a time.

1. Verify SPEC.md says APPROVED and `.syncagent/TASKS.json` validates. If not, stop.
2. Loop until `tasks next` reports nothing ready:
   - `{cli} tasks next`
   - `{cli} tasks start <id>`
   - implement exactly that task
   - `{cli} tasks done <id>`   (stamps it and commits as "<id>: <title>")
3. One task per commit. Do not batch several tasks into one commit.
4. If a task turns out to be impossible or wrong, `{cli} tasks block <id> --reason "..."`
   and move on rather than improvising around it.
5. Update `.syncagent/STATUS.md` as you go - the user watches it live.
6. `{cli} gate {build}`
7. Do not self-review. That is the next phase and a different agent.
""",
        "review.md": f"""Run a review round.

1. `{cli} ask gemini --role review` (it captures the diff itself)
2. Read `.syncagent/reviews/`. Discard findings with no file/line.
3. Fix every BLOCKER. List MAJORs for the user. Ignore NITs.
4. If you think a BLOCKER is wrong and it matters, write a test or call
   `{cli} ask codex --role tiebreak --text "<both positions>"`.
   Log the result in DECISIONS.md.
5. Second round maximum. Then escalate to the user whatever is left.
""",
        "wrap.md": f"""Close out the current cycle.

1. One final Codex pass if the work is substantial and you have not used it yet:
   `{cli} ask codex --role review`
2. Update STATUS.md with what shipped and what is deliberately left undone.
3. Append anything contested to DECISIONS.md.
4. `{cli} gate done`
5. Give the user a five-line summary. Not more.
""",
    }


def cmd_init(args):
    root = Path(args.path).expanduser().resolve()
    if (root / ORCH).exists() and not args.force:
        sys.exit(f"{root/ORCH} already exists. Use --force to overwrite the scaffold.")

    name = args.name or root.name
    track = args.track
    cli = cli_invocation()

    for d in ["", "reviews", "research", "inputs", "refs", "prompts"]:
        (root / ORCH / d).mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "commands").mkdir(parents=True, exist_ok=True)

    files = {
        root / ORCH / "SPEC.md": spec_template(track, name),
        root / ORCH / "QUESTIONS.md": QUESTIONS_TEMPLATE,
        root / ORCH / "STATUS.md": STATUS_TEMPLATE,
        root / ORCH / "DECISIONS.md": DECISIONS_TEMPLATE,
        root / ORCH / "RESEARCH.md": "# Research\n\n_Written by Gemini. Empty until the research phase runs._\n",
        root / "CLAUDE.md": claude_md(track, name, cli),
        root / "GEMINI.md": gemini_md(name),
        root / "AGENTS.md": agents_md(name),
        root / ORCH / "refs" / "README.md": (
            "# refs\n\nRead-only material linked from outside this workspace.\n\n"
            f"Add with: `{cli} ref /path/to/folder`\n\n"
            "Writes here are denied in .claude/settings.json, and deny rules hold "
            "even under --dangerously-skip-permissions.\n"
        ),
    }
    for path, body in files.items():
        if path.exists() and not args.force:
            continue
        path.write_text(body, encoding="utf-8")

    for fname, body in prompt_files(track).items():
        (root / ORCH / "prompts" / fname).write_text(body, encoding="utf-8")

    for fname, body in slash_commands(track, cli).items():
        (root / ".claude" / "commands" / fname).write_text(body, encoding="utf-8")

    write_json(root / ".claude" / "settings.json", claude_settings())

    write_json(root / ORCH / "config.json", {
        "version": VERSION,
        "name": name,
        "track": track,
        "created": now_iso(),
        "agents": {
            "claude": {"model": "opus", "effort": "high", "role": "implement + orchestrate",
                       "budget_tokens_per_day": 2000000},
            "gemini": {"model": "gemini-2.5-pro", "effort": "default", "role": "research + review",
                       "budget_tokens_per_day": 1000000},
            "codex":  {"model": "gpt-5-codex", "effort": "medium", "role": "tiebreak only",
                       "budget_tokens_per_day": 120000},
        },
        # Edit these once you know your own ceiling. `usage --plan max-20x` and
        # `usage --window-tokens N` write the same block.
        "limits": dict(DEFAULT_LIMITS),
    })

    write_json(root / ORCH / "state.json", {
        "phase": "align",
        "gates": TRACKS[track]["gates"],
        "review_round": 0,
        "session_started": now_iso(),
        "updated": now_iso(),
    })

    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(".syncagent/telemetry.jsonl\n.syncagent/refs/\n.claude/settings.local.json\n",
                      encoding="utf-8")

    if have("git") and not (root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=root, check=False)

    print(f"Workspace ready: {root}")
    print(f"Track: {TRACKS[track]['label']}")
    print()
    print("Next:")
    print(f"  cd {root}")
    print(f"  {cli} start")
    print(f"  {cli} dash")


# --------------------------------------------------------------------------
# ref - link outside material read-only
# --------------------------------------------------------------------------

def cmd_ref(args):
    root = find_root()
    src = Path(args.path).expanduser().resolve()
    if not src.exists():
        sys.exit(f"No such path: {src}")

    dest = root / ORCH / "refs" / (args.rename or src.name)
    if dest.exists():
        sys.exit(f"Already linked: {dest}")

    if args.copy:
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        mode = "copied"
    else:
        try:
            dest.symlink_to(src, target_is_directory=src.is_dir())
            mode = "linked"
        except OSError:
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            mode = "copied (symlink unavailable)"

    log_event(root, {"kind": "ref", "path": str(src), "mode": mode})
    print(f"{mode}: {src} -> {dest}")
    print("Agents can read it. Writes are denied by .claude/settings.json.")


# --------------------------------------------------------------------------
# ask - run a consultant agent headless
# --------------------------------------------------------------------------

DIFF_CHAR_CAP = 180_000


def collect_change(root, cap=DIFF_CHAR_CAP):
    """Everything that changed, including files git does not track yet.

    A fresh `git init` has no HEAD, so `git diff HEAD` fails. And plain `git diff`
    never shows brand-new files - which is most of what an agent produces. Both
    cases have to be handled or reviews silently see nothing.
    """
    if not have("git"):
        return ""

    def git(*a):
        return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)

    has_head = git("rev-parse", "--verify", "HEAD").returncode == 0
    parts = []

    tracked = git("diff", "HEAD").stdout if has_head else (
        git("diff", "--cached").stdout + git("diff").stdout)
    if tracked.strip():
        parts.append(tracked)

    skip_dirs = (".syncagent/", ".claude/", ".git/")
    skip_files = {"CLAUDE.md", "GEMINI.md", "AGENTS.md", ".gitignore"}
    untracked = [f for f in git("ls-files", "--others", "--exclude-standard").stdout.splitlines()
                 if f.strip() and not f.startswith(skip_dirs) and f not in skip_files]

    for rel in untracked[:60]:
        path = root / rel
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 120_000:
                parts.append(f"--- new file (too large to inline): {rel} ---")
                continue
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            parts.append(f"--- new file (binary or unreadable): {rel} ---")
            continue
        parts.append(f"--- new file: {rel} ---\n{body}")

    out = "\n\n".join(parts)
    if len(out) > cap:
        out = out[:cap] + f"\n\n[truncated at {cap:,} characters - review the rest separately]"
    return out


def build_prompt(root, role, text, include_diff):
    prompt_path = root / ORCH / "prompts" / f"{role}.md"
    if not prompt_path.exists():
        sys.exit(f"No prompt template for role '{role}'. Expected {prompt_path}")
    template = prompt_path.read_text(encoding="utf-8")

    spec = (root / ORCH / "SPEC.md").read_text(encoding="utf-8") if (root / ORCH / "SPEC.md").exists() else ""

    body = text or ""
    if include_diff:
        change = collect_change(root)
        if change.strip():
            body = (body + "\n\n" if body else "") + "```diff\n" + change + "\n```"
        else:
            body = (body + "\n\n" if body else "") + "(no changes detected in the workspace)"

    return template.replace("{SPEC}", spec).replace("{INPUT}", body)


def strip_fences(text):
    """Models wrap JSON in ```json fences even when told not to."""
    t = (text or "").strip()
    m = re.match(r"^```[A-Za-z0-9_+-]*\s*\n(.*?)\n?```$", t, re.S)
    return m.group(1).strip() if m else t


def parse_gemini(stdout):
    """Gemini --output-format json: {response, stats:{models:{name:{tokens:{...}}}}}"""
    try:
        data = json.loads(strip_fences(stdout))
    except json.JSONDecodeError:
        return stdout, {}
    text = data.get("response", "")
    tokens = {}
    models = (data.get("stats") or {}).get("models") or {}
    for model_name, stats in models.items():
        tk = stats.get("tokens") or {}
        tokens = {
            "model": model_name,
            "in": tk.get("prompt", 0),
            "out": tk.get("candidates", tk.get("response", 0)),
            "total": tk.get("total", 0),
        }
        break
    return text, tokens


def parse_codex(stdout):
    """Codex --json emits JSONL events. Take the last agent message and last usage."""
    text_parts, tokens = [], {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        item = ev.get("item") or {}
        if item.get("type") in ("agent_message", "assistant_message"):
            t = item.get("text") or item.get("content") or ""
            if isinstance(t, str) and t.strip():
                text_parts.append(t)
        if isinstance(ev.get("text"), str) and ev.get("type", "").startswith("item"):
            text_parts.append(ev["text"])

        usage = ev.get("usage") or (ev.get("turn") or {}).get("usage")
        if isinstance(usage, dict):
            tokens = {
                "model": ev.get("model", "codex"),
                "in": usage.get("input_tokens", 0),
                "out": usage.get("output_tokens", 0),
                "total": usage.get("total_tokens",
                                   usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
            }
    return ("\n".join(text_parts).strip() or stdout), tokens


def cmd_ask(args):
    root = find_root()
    cfg = read_json(root / ORCH / "config.json")
    agent = args.agent
    role = args.role

    if agent == "codex":
        used = [e for e in load_telemetry(root)
                if e.get("agent") == "codex" and e.get("kind") == "ask"]
        if used and not args.force:
            spent = sum(e.get("tokens_total", 0) for e in used)
            print(f"note: codex has already run {len(used)}x this project (~{spent:,} tokens).")
            print("      it is meant to be the tiebreaker, not a participant.")

    if not have(agent if agent != "gemini" else "gemini"):
        sys.exit(f"'{agent}' is not on your PATH.")

    prompt = build_prompt(root, role, args.text, include_diff=(role == "review"))
    started = time.time()

    if agent == "gemini":
        # Prompt goes over stdin. Passing it as an argv string hits ARG_MAX once
        # the spec and diff grow, and the failure looks like an unrelated crash.
        cmd = [exe("gemini"), "--output-format", "json"]
        model = cfg.get("agents", {}).get("gemini", {}).get("model")
        if model:
            cmd += ["-m", model]
        proc = subprocess.run(cmd, cwd=root, input=prompt, capture_output=True, text=True)
        answer, tokens = parse_gemini(proc.stdout)
    else:
        cmd = [exe("codex"), "exec", "-", "--json", "--sandbox", "read-only", "--ephemeral",
               "--skip-git-repo-check"]
        model = cfg.get("agents", {}).get("codex", {}).get("model")
        if model:
            cmd += ["--model", model]
        effort = cfg.get("agents", {}).get("codex", {}).get("effort")
        if effort:
            cmd += ["-c", f"model_reasoning_effort={effort}"]
        proc = subprocess.run(cmd, cwd=root, input=prompt, capture_output=True, text=True)
        answer, tokens = parse_codex(proc.stdout)

    elapsed = int((time.time() - started) * 1000)

    if role in ("review", "tiebreak"):
        answer = strip_fences(answer)

    if proc.returncode != 0 and not answer.strip():
        log_event(root, {"kind": "ask", "agent": agent, "role": role, "ok": False,
                         "duration_ms": elapsed, "error": (proc.stderr or "")[:400]})
        sys.exit(f"{agent} failed (exit {proc.returncode}):\n{proc.stderr[:1200]}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if role == "review":
        out = root / ORCH / "reviews" / f"{stamp}-{agent}.md"
    elif role == "research":
        out = root / ORCH / "RESEARCH.md"
    else:
        out = root / ORCH / "research" / f"{stamp}-{agent}-{role}.md"

    header = f"<!-- {agent} / {role} / {now_iso()} -->\n\n"
    if role == "research" and out.exists():
        with open(out, "a", encoding="utf-8") as fh:
            fh.write("\n\n---\n\n" + header + answer + "\n")
    else:
        out.write_text(header + answer + "\n", encoding="utf-8")

    log_event(root, {
        "kind": "ask", "agent": agent, "role": role, "ok": True,
        "model": tokens.get("model") or cfg.get("agents", {}).get(agent, {}).get("model", agent),
        "effort": cfg.get("agents", {}).get(agent, {}).get("effort", "default"),
        "tokens_in": tokens.get("in", 0),
        "tokens_out": tokens.get("out", 0),
        "tokens_total": tokens.get("total", 0),
        "duration_ms": elapsed,
        "output": str(out.relative_to(root)),
    })

    print(f"{agent}/{role} -> {out.relative_to(root)}  "
          f"({tokens.get('total', 0):,} tokens, {elapsed/1000:.1f}s)")
    if args.show:
        print()
        print(answer)


# --------------------------------------------------------------------------
# tasks - the ledger on disk
# --------------------------------------------------------------------------

def read_tasks_doc(path):
    """(doc, error). Never rewrites a file it could not parse."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as e:
        return None, f"{path.name} is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})"
    except OSError as e:
        return None, f"cannot read {path.name}: {e}"


def load_tasks(root):
    path = root / ORCH / TASKS
    if not path.exists():
        sys.exit(f"No {TASKS} yet. Run /plan in Claude to build the roadmap first.")
    doc, err = read_tasks_doc(path)
    if err:
        sys.exit(err)
    if not isinstance(doc, dict) or not isinstance(doc.get("tasks"), list):
        sys.exit(f"{TASKS} has no 'tasks' list.")
    return doc


def save_tasks(root, doc):
    """Whole-file read-modify-write. Single user, so a lock would be theatre."""
    doc["updated"] = now_iso()
    write_json(root / ORCH / TASKS, doc)


def get_task(doc, tid):
    for t in doc["tasks"]:
        if t.get("id") == tid:
            return t
    sys.exit(f"No task with id '{tid}'. Run 'tasks list' to see the roadmap.")


def git_ok(root):
    return have("git") and (root / ".git").exists()


def cmd_tasks_validate(args):
    root = find_root()
    doc = load_tasks(root)
    errors, warnings = validate_tasks(doc)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        print()
        for e in errors:
            print(f"error: {e}")
        sys.exit(1)
    print(f"{TASKS} is valid ({len(doc['tasks'])} tasks).")


def cmd_tasks_next(args):
    root = find_root()
    doc = load_tasks(root)
    ready = ready_tasks(doc["tasks"])
    if not ready:
        blocked = [t for t in doc["tasks"] if t.get("status") == "blocked"]
        doing = [t for t in doc["tasks"] if t.get("status") == "doing"]
        if all(t.get("status") == "done" for t in doc["tasks"]) and doc["tasks"]:
            sys.exit("roadmap complete")
        detail = ""
        if doing:
            detail = f" ({len(doing)} in progress: {', '.join(t['id'] for t in doing)})"
        elif blocked:
            detail = f" ({len(blocked)} blocked: {', '.join(t['id'] for t in blocked)})"
        sys.exit(f"nothing ready{detail}")
    print(json.dumps(ready[0], indent=2))


def cmd_tasks_parallel(args):
    root = find_root()
    doc = load_tasks(root)
    batch = parallel_batch(ready_tasks(doc["tasks"]), args.max)
    if not batch:
        sys.exit("nothing ready")
    print(json.dumps(batch, indent=2))
    if len(batch) == 1 and not (batch[0].get("files") or []):
        print(f"\nnote: {batch[0]['id']} has no declared files, so its footprint is "
              f"unknown and it runs alone.", file=sys.stderr)


def cmd_tasks_start(args):
    root = find_root()
    doc = load_tasks(root)
    task = get_task(doc, args.id)

    done = {t["id"] for t in doc["tasks"] if t.get("status") == "done"}
    unmet = [d for d in (task.get("depends_on") or []) if d not in done]
    if unmet and not args.force:
        sys.exit(f"{task['id']} depends on {', '.join(unmet)}, which "
                 f"{'is' if len(unmet) == 1 else 'are'} not done yet.")
    if task.get("status") == "done":
        print(f"warning: {task['id']} was already done. Reopening it.")

    task["status"] = "doing"
    task["started"] = now_iso()
    save_tasks(root, doc)
    log_event(root, {"kind": "task", "task": task["id"], "status": "doing",
                     "agent": task.get("assignee", "claude")})
    print(f"{task['id']} -> doing   {task.get('title', '')}")


def cmd_tasks_done(args):
    root = find_root()
    doc = load_tasks(root)
    task = get_task(doc, args.id)

    task["status"] = "done"
    task["finished"] = now_iso()
    save_tasks(root, doc)

    sha = None
    if args.no_commit:
        pass
    elif not git_ok(root):
        print("warning: not a git repository, so no checkpoint was made. "
              "The ledger is updated.")
    else:
        def git(*a):
            return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)

        if not git("status", "--porcelain").stdout.strip():
            print(f"warning: the working tree was already clean before {task['id']} was "
                  f"marked done. That usually means the task changed nothing.")
        git("add", "-A")
        msg = f"{task['id']}: {task.get('title', '').strip()}".rstrip(": ")
        commit = git("commit", "-m", msg)
        if commit.returncode == 0:
            sha = git("rev-parse", "HEAD").stdout.strip() or None
            task["commit"] = sha
            save_tasks(root, doc)
        else:
            print(f"warning: commit failed, ledger still updated.\n"
                  f"  {(commit.stderr or commit.stdout).strip()[:300]}")

    log_event(root, {"kind": "task", "task": task["id"], "status": "done",
                     "agent": task.get("assignee", "claude"), "commit": sha})

    summary = tasks_summary(doc["tasks"])
    print(f"{task['id']} -> done   {task.get('title', '')}"
          + (f"   [{sha[:8]}]" if sha else ""))
    print(f"{summary['done']}/{summary['total']} tasks, "
          f"{summary['value_percent']}% by value")


def cmd_tasks_block(args):
    root = find_root()
    doc = load_tasks(root)
    task = get_task(doc, args.id)
    task["status"] = "blocked"
    note = (task.get("notes") or "").strip()
    task["notes"] = (note + "\n" if note else "") + f"[{now_iso()}] blocked: {args.reason}"
    save_tasks(root, doc)
    log_event(root, {"kind": "task", "task": task["id"], "status": "blocked",
                     "note": args.reason})
    print(f"{task['id']} -> blocked   {args.reason}")


GLYPH = {"todo": " ", "doing": ">", "done": "x", "blocked": "!"}


def cmd_tasks_list(args):
    root = find_root()
    doc = load_tasks(root)
    tasks = doc["tasks"]
    if not tasks:
        sys.exit("The roadmap is empty.")

    ordered_ready = ready_tasks(tasks)
    ready = {t["id"] for t in ordered_ready}
    next_id = ordered_ready[0]["id"] if ordered_ready else None
    width = max(len(t.get("id", "")) for t in tasks)
    for t in sorted(tasks, key=lambda x: natural_key(x.get("id", ""))):
        mark = GLYPH.get(t.get("status", "todo"), "?")
        flag = "<-- next" if t.get("id") == next_id else ""
        print(f"  [{mark}] {t.get('id', ''):<{width}}  {t.get('value', '-'):<6} "
              f"{t.get('size', '-'):<2} {t.get('assignee', '-'):<7} "
              f"{t.get('title', '')[:44]:<44} {flag}")

    s = tasks_summary(tasks)
    print(f"\n{s['done']}/{s['total']} done, {s['value_percent']}% by value, "
          f"{len(ready)} ready")


def cmd_resume(args):
    """The cheap path back into an interrupted session.

    Deliberately narrow: no repository read, no spec restatement. A resumed session
    should start from a small fixed payload instead of rediscovering the plan, which
    is the most expensive thing it could possibly do.
    """
    root = find_root()
    cfg = read_json(root / ORCH / "config.json")
    state = read_json(root / ORCH / "state.json")
    spec_path = root / ORCH / "SPEC.md"
    approved = spec_path.exists() and "STATUS: APPROVED" in spec_path.read_text(encoding="utf-8")

    print(f"{cfg.get('name', root.name)}  [{TRACKS.get(cfg.get('track', 'generic'), TRACKS['generic'])['label']}]")
    print(f"phase: {state.get('phase', 'align')}   "
          f"spec: {'APPROVED' if approved else 'DRAFT'}")

    path = root / ORCH / TASKS
    if not path.exists():
        print(f"\nNo roadmap yet ({TASKS} absent). Run /plan.")
        return
    doc = load_tasks(root)
    tasks = doc["tasks"]
    s = tasks_summary(tasks)
    print(f"tasks: {s['done']}/{s['total']} done, {s['value_percent']}% by value")

    stalled = [t for t in tasks if t.get("status") == "doing"]
    if stalled:
        print()
        for t in stalled:
            t["status"] = "todo"
            t["started"] = None
            print(f"reset {t['id']} from doing -> todo. The previous session died "
                  f"mid-task, so its partial work may be uncommitted.")
        print("Check `git status` before continuing.")
        save_tasks(root, doc)

    ready = ready_tasks(tasks)
    print()
    if ready:
        print("Next task:")
        print(json.dumps(ready[0], indent=2))
    elif tasks and all(t.get("status") == "done" for t in tasks):
        print("Roadmap complete.")
    else:
        print("Nothing ready.")

    blocked = [t for t in tasks if t.get("status") == "blocked"]
    if blocked:
        print("\nBlocked:")
        for t in blocked:
            reason = (t.get("notes") or "").strip().splitlines()
            print(f"  {t['id']}  {t.get('title', '')}"
                  + (f"\n      {reason[-1]}" if reason else ""))


# --------------------------------------------------------------------------
# gate / status
# --------------------------------------------------------------------------

def cmd_gate(args):
    root = find_root()
    state = read_json(root / ORCH / "state.json")
    if args.phase not in state.get("gates", []):
        sys.exit(f"Unknown phase. Valid: {', '.join(state.get('gates', []))}")

    spec = (root / ORCH / "SPEC.md").read_text(encoding="utf-8")
    approved = "STATUS: APPROVED" in spec
    if args.phase not in ("align",) and not approved:
        sys.exit("SPEC.md is not APPROVED yet. Nothing past alignment can start.")

    if args.phase in ("build", "draft"):
        # A roadmap that does not validate is worse than no roadmap: the agent will
        # follow it anyway. Workspaces created before the ledger existed have no
        # TASKS.json at all, and those must keep working.
        path = root / ORCH / TASKS
        if path.exists():
            doc, err = read_tasks_doc(path)
            if err:
                sys.exit(f"TASKS.json is unusable, so {args.phase} cannot start.\n  {err}")
            errors, _ = validate_tasks(doc)
            if errors:
                sys.exit(f"TASKS.json does not validate, so {args.phase} cannot start:\n  "
                         + "\n  ".join(errors))
        else:
            print("note: no TASKS.json. Run /plan first, or continue without a roadmap.")

    if args.phase == "review":
        state["review_round"] = state.get("review_round", 0) + 1
        if state["review_round"] > 2:
            print("warning: this is review round 3+. Escalate to a human instead.")
    if args.phase in ("build", "draft"):
        state["review_round"] = 0

    state["phase"] = args.phase
    state["updated"] = now_iso()
    write_json(root / ORCH / "state.json", state)
    log_event(root, {"kind": "gate", "phase": args.phase})
    print(f"phase -> {args.phase}")


# --------------------------------------------------------------------------
# live Claude usage - measured off the local session transcripts
# --------------------------------------------------------------------------
#
# Claude Code appends every assistant turn, with the exact usage block the API
# returned, to ~/.claude/projects/<slugged-cwd>/<session-id>.jsonl. That file is
# the only real-time source of truth for what this session has actually spent.
# The `log` command is a self-report Claude has to remember to make, and a
# self-report always undercounts, which is why the dashboard used to disagree
# with reality.

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# Subscription limits are consumption budgets, not message counts, and the four
# token classes are nowhere near equal: a cached read costs a tenth of a fresh
# input token and an output token costs five times one. Weighting each class by
# its relative price is what makes a single "how much is left" number honest.
TOKEN_WEIGHTS = {"input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1}

# Anthropic does not publish the subscription ceilings in tokens, so these are
# calibrated estimates rather than quoted figures. They are written into
# config.json exactly so that a user who hits a limit at 60% can correct them:
#   syncagent.py usage --calibrate
PLAN_LIMITS = {
    "pro":     {"window":  2_000_000, "weekly":  25_000_000},
    "max-5x":  {"window": 10_000_000, "weekly": 125_000_000},
    "max-20x": {"window": 40_000_000, "weekly": 500_000_000},
}
DEFAULT_LIMITS = {
    "plan": "max-5x",
    "window_hours": 5,
    "window_tokens": PLAN_LIMITS["max-5x"]["window"],
    "weekly_tokens": PLAN_LIMITS["max-5x"]["weekly"],
    "weights": TOKEN_WEIGHTS,
}
USAGE_KEYS = ("input", "output", "cache_write", "cache_read", "total", "weighted")


def parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def project_slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def _transcript_cwd(path, max_lines=60):
    """The workspace a transcript belongs to, as it recorded it itself."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                if '"cwd"' not in line:
                    continue
                try:
                    cwd = json.loads(line).get("cwd")
                except json.JSONDecodeError:
                    continue
                if cwd:
                    return str(Path(cwd)).lower()
    except OSError:
        pass
    return None


def transcript_dir(root):
    direct = CLAUDE_PROJECTS / project_slug(root)
    if direct.is_dir():
        return direct
    # The slug rule has changed between Claude Code versions. Rather than guess
    # at it, ask the transcripts which one recorded this workspace.
    if not CLAUDE_PROJECTS.is_dir():
        return None
    target = str(Path(root).resolve()).lower()
    for d in sorted(CLAUDE_PROJECTS.iterdir()):
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            if _transcript_cwd(f) == target:
                return d
    return None


def _usage_record(entry, weights):
    msg = entry.get("message") or {}
    u = msg.get("usage")
    ts = parse_ts(entry.get("timestamp"))
    if not isinstance(u, dict) or ts is None:
        return None
    counts = {
        "input": int(u.get("input_tokens") or 0),
        "output": int(u.get("output_tokens") or 0),
        "cache_write": int(u.get("cache_creation_input_tokens") or 0),
        "cache_read": int(u.get("cache_read_input_tokens") or 0),
    }
    rec = dict(counts)
    rec["total"] = sum(counts.values())
    rec["weighted"] = round(sum(counts[k] * weights.get(k, 1.0) for k in counts))
    rec["ts"] = ts
    rec["session"] = entry.get("sessionId") or ""
    rec["model"] = msg.get("model") or "unknown"
    return rec


def read_claude_usage(root, weights=None):
    """Every assistant turn this workspace has produced, deduplicated.

    Resumed and forked sessions copy earlier turns into the new transcript, so
    the same API call appears in several files. Keying on the message id counts
    each call exactly once.
    """
    weights = weights or TOKEN_WEIGHTS
    d = transcript_dir(root)
    if not d:
        return []
    seen, out = set(), []
    for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                key = (entry.get("message") or {}).get("id") or entry.get("requestId")
                if key:
                    if key in seen:
                        continue
                    seen.add(key)
                rec = _usage_record(entry, weights)
                if rec:
                    out.append(rec)
    out.sort(key=lambda r: r["ts"])
    return out


def _sum_usage(records):
    agg = {k: sum(r[k] for r in records) for k in USAGE_KEYS}
    agg["calls"] = len(records)
    agg["first"] = records[0]["ts"].isoformat() if records else None
    agg["last"] = records[-1]["ts"].isoformat() if records else None
    return agg


def _bucket(records, used, limit, now, window=None):
    """A spend bucket plus the two numbers a human actually wants: what fraction
    of the ceiling is gone, and when the ceiling stops applying."""
    block = _sum_usage(records)
    block["limit"] = limit
    block["remaining"] = max(limit - used, 0) if limit else 0
    block["percent"] = round(min(used / limit, 1.0) * 100, 1) if limit else 0.0
    block["over"] = bool(limit and used > limit)
    if window and records:
        block["resets"] = (records[0]["ts"] + window).isoformat()
        block["resets_in_hours"] = round(
            max((records[0]["ts"] + window - now).total_seconds(), 0) / 3600, 2)
    else:
        block["resets"] = None
        block["resets_in_hours"] = None
    return block


def resolve_limits(cfg):
    """Config wins over the plan preset, the preset wins over the default."""
    configured = cfg.get("limits") or {}
    limits = dict(DEFAULT_LIMITS)
    preset = PLAN_LIMITS.get(configured.get("plan", limits["plan"]))
    if preset:
        limits["window_tokens"] = preset["window"]
        limits["weekly_tokens"] = preset["weekly"]
    limits.update(configured)
    weights = dict(TOKEN_WEIGHTS)
    weights.update(limits.get("weights") or {})
    limits["weights"] = weights
    return limits


def claude_usage_report(root, cfg=None):
    """What this workspace has spent, over the three windows that matter: the
    live session, the rolling subscription window, and the week."""
    cfg = cfg if cfg is not None else read_json(root / ORCH / "config.json")
    limits = resolve_limits(cfg)
    weights = limits["weights"]
    records = read_claude_usage(root, weights)

    now = datetime.now(timezone.utc)
    window = timedelta(hours=float(limits.get("window_hours") or 5))
    win_limit = int(limits.get("window_tokens") or 0)
    week_limit = int(limits.get("weekly_tokens") or 0)

    report = {
        "available": bool(records),
        "source": str(transcript_dir(root) or ""),
        "plan": limits.get("plan", "custom"),
        "window_hours": window.total_seconds() / 3600,
        "weights": weights,
        "estimated_limits": True,
        "updated": now.isoformat(timespec="seconds"),
    }
    if not records:
        report["reason"] = ("No Claude Code transcripts found for this workspace. "
                            "Run Claude from inside it and the meter fills itself.")
        return report

    in_window = [r for r in records if r["ts"] >= now - window]
    in_week = [r for r in records if r["ts"] >= now - timedelta(days=7)]
    in_day = [r for r in records if r["ts"] >= now - timedelta(days=1)]

    win_used = sum(r["weighted"] for r in in_window)
    week_used = sum(r["weighted"] for r in in_week)

    session_id = records[-1]["session"]
    session = [r for r in records if r["session"] == session_id]

    report["session"] = _sum_usage(session)
    report["session"]["id"] = session_id
    report["day"] = _sum_usage(in_day)
    report["window"] = _bucket(in_window, win_used, win_limit, now, window)
    report["week"] = _bucket(in_week, week_used, week_limit, now, timedelta(days=7))

    # Burn rate from the last hour, because that is what "how much longer can I
    # keep working" depends on. With too little recent traffic to extrapolate
    # from, fall back to the average across the whole window.
    recent = [r for r in records if r["ts"] >= now - timedelta(hours=1)]
    if len(recent) >= 2:
        burn = sum(r["weighted"] for r in recent)
    elif in_window:
        elapsed = max((now - in_window[0]["ts"]).total_seconds() / 3600, 0.05)
        burn = win_used / elapsed
    else:
        burn = 0.0
    report["burn_per_hour"] = round(burn)

    hours_left = None
    if burn > 0:
        candidates = [b["remaining"] / burn for b in (report["window"], report["week"])
                      if b["limit"]]
        if candidates:
            hours_left = min(candidates)
    report["hours_left"] = round(hours_left, 2) if hours_left is not None else None
    report["runs_out"] = ((now + timedelta(hours=hours_left)).isoformat(timespec="seconds")
                          if hours_left is not None else None)
    report["binding"] = ("week" if report["week"]["limit"] and report["window"]["limit"]
                         and report["week"]["percent"] > report["window"]["percent"]
                         else "window")

    by_model = {}
    for r in session:
        blank = dict.fromkeys(USAGE_KEYS, 0)
        blank["calls"] = 0
        m = by_model.setdefault(r["model"], blank)
        for k in USAGE_KEYS:
            m[k] += r[k]
        m["calls"] += 1
    report["by_model"] = by_model
    return report


# How long an agent may go quiet before the panel stops calling it live. Claude
# streams a transcript line every few seconds while it works; gemini and codex
# are one-shot, so a recent call is the only evidence they were ever here.
LIVE_SECONDS = 90
IDLE_SECONDS = 15 * 60


def agent_state(installed, idle_seconds):
    if not installed:
        return "missing"
    if idle_seconds is None:
        return "never"
    if idle_seconds <= LIVE_SECONDS:
        return "live"
    if idle_seconds <= IDLE_SECONDS:
        return "idle"
    return "cold"


def collect_status(root):
    cfg = read_json(root / ORCH / "config.json")
    state = read_json(root / ORCH / "state.json")
    events = load_telemetry(root)

    spec_text = ""
    spec_path = root / ORCH / "SPEC.md"
    if spec_path.exists():
        spec_text = spec_path.read_text(encoding="utf-8")
    approved = "STATUS: APPROVED" in spec_text

    questions = []
    q_path = root / ORCH / "QUESTIONS.md"
    if q_path.exists():
        in_fence = False
        for line in q_path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = re.match(r"\s*-\s*\[( |x|X)\]\s*(.+)", line)
            if m:
                questions.append({"answered": m.group(1).lower() == "x",
                                  "text": m.group(2).strip()})

    per_agent = {}
    for name, meta in (cfg.get("agents") or {}).items():
        calls = [e for e in events if e.get("agent") == name and e.get("kind") == "ask"]
        per_agent[name] = {
            "model": meta.get("model", "-"),
            "effort": meta.get("effort", "-"),
            "role": meta.get("role", "-"),
            "budget": meta.get("budget_tokens_per_day", 0),
            "calls": len(calls),
            "tokens": sum(e.get("tokens_total", 0) for e in calls),
            "seconds": round(sum(e.get("duration_ms", 0) for e in calls) / 1000, 1),
            "last": calls[-1]["ts"] if calls else None,
            "measured": False,
        }

    # Claude's own row came from self-reported `log` events, which is why it
    # never matched what the subscription was actually being charged. Where the
    # transcripts exist they replace the guess with the measurement.
    usage = claude_usage_report(root, cfg)
    if usage.get("available") and "claude" in per_agent:
        row = per_agent["claude"]
        row["tokens"] = usage["day"]["weighted"]
        row["calls"] = usage["day"]["calls"]
        row["last"] = usage["day"]["last"]
        row["measured"] = True

    # An agent listed in config.json is a plan, not a pulse. A panel that shows
    # gemini sitting there long after it stopped answering is worse than one
    # that shows nothing, so every row carries when it was last actually heard
    # from and whether its binary is even installed.
    now = datetime.now(timezone.utc)
    for name, row in per_agent.items():
        row["installed"] = have(name)
        seen = parse_ts(row.get("last"))
        row["idle_seconds"] = round((now - seen).total_seconds()) if seen else None
        row["state"] = agent_state(row["installed"], row["idle_seconds"])

    session_start = state.get("session_started", "")
    noise = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist",
             "build", ".next", "target", ".pytest_cache", ".mypy_cache"}
    made, fed = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        parts = rel.parts
        if noise.intersection(parts[:-1]):
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        except OSError:
            continue
        entry = {"path": str(rel), "mtime": mtime, "size": p.stat().st_size}
        if len(parts) >= 2 and parts[0] == ORCH and parts[1] in ("refs", "inputs"):
            fed.append(entry)
        elif session_start and mtime >= session_start:
            made.append(entry)

    made.sort(key=lambda e: e["mtime"], reverse=True)

    tasks_block = None
    tasks_path = root / ORCH / TASKS
    if tasks_path.exists():
        doc, err = read_tasks_doc(tasks_path)
        if err:
            tasks_block = {"error": err}
        elif isinstance(doc, dict) and isinstance(doc.get("tasks"), list):
            tasks_block = tasks_summary(doc["tasks"])

    return {
        "name": cfg.get("name", root.name),
        "track": cfg.get("track", "generic"),
        "track_label": TRACKS.get(cfg.get("track", "generic"), TRACKS["generic"])["label"],
        "phase": state.get("phase", "align"),
        "gates": state.get("gates", []),
        "review_round": state.get("review_round", 0),
        "approved": approved,
        "questions": questions,
        "pending_questions": [q for q in questions if not q["answered"]],
        "tasks": tasks_block,
        "agents": per_agent,
        "usage": usage,
        "events": events[-40:][::-1],
        "files_made": made[:40],
        "files_fed": fed[:40],
        "status_md": (root / ORCH / "STATUS.md").read_text(encoding="utf-8")
                     if (root / ORCH / "STATUS.md").exists() else "",
        "updated": now_iso(),
    }


def cmd_log(args):
    """Claude self-reports its own work, since an interactive session cannot be
    instrumented from the outside."""
    root = find_root()
    log_event(root, {
        "kind": "ask", "agent": "claude", "role": args.role, "ok": True,
        "model": read_json(root / ORCH / "config.json").get(
            "agents", {}).get("claude", {}).get("model", "opus"),
        "effort": "high",
        "tokens_total": args.tokens,
        "duration_ms": 0,
        "note": args.note,
    })
    print(f"logged claude/{args.role} ({args.tokens:,} tok)")


def _meter_bar(percent, width=28):
    lit = int(round(min(percent, 100) / 100 * width))
    return "[" + "#" * lit + "." * (width - lit) + "]"


def _fmt_hours(hours):
    if hours is None:
        return "unknown"
    h, m = int(hours), int(round((hours - int(hours)) * 60))
    return f"{h}h {m:02d}m" if h else f"{m}m"


def cmd_usage(args):
    root = find_root()
    cfg_path = root / ORCH / "config.json"
    cfg = read_json(cfg_path)

    if args.plan or args.window_tokens or args.weekly_tokens:
        limits = dict(cfg.get("limits") or {})
        if args.plan:
            limits["plan"] = args.plan
            preset = PLAN_LIMITS.get(args.plan)
            if preset:
                limits["window_tokens"] = preset["window"]
                limits["weekly_tokens"] = preset["weekly"]
        if args.window_tokens:
            limits["window_tokens"] = args.window_tokens
        if args.weekly_tokens:
            limits["weekly_tokens"] = args.weekly_tokens
        cfg["limits"] = limits
        write_json(cfg_path, cfg)
        print(f"limits updated in {cfg_path.relative_to(root)}")

    u = claude_usage_report(root, cfg)
    if args.json:
        print(json.dumps(u, indent=2))
        return
    if not u.get("available"):
        print(u.get("reason", "No measured Claude usage yet."))
        print(f"looked in: {u.get('source') or CLAUDE_PROJECTS}")
        return

    s, w, k = u["session"], u["window"], u["week"]
    print(f"plan {u['plan']}  -  weighted tokens (output x{u['weights']['output']:g}, "
          f"cache read x{u['weights']['cache_read']:g})")
    print()
    print(f"this session   {s['calls']:>4} calls  {s['total']:>12,} raw  "
          f"{s['weighted']:>12,} weighted")
    print(f"  in {s['input']:,} / out {s['output']:,} / "
          f"cache write {s['cache_write']:,} / cache read {s['cache_read']:,}")
    print()
    win_label = f"{u['window_hours']:g}h window"
    print(f"{win_label:<14} {_meter_bar(w['percent'])} {w['percent']:>5.1f}%"
          f"   {w['weighted']:,} / {w['limit']:,}")
    print(f"{'':<14} resets in {_fmt_hours(w['resets_in_hours'])}")
    print(f"{'7d window':<14} {_meter_bar(k['percent'])} {k['percent']:>5.1f}%"
          f"   {k['weighted']:,} / {k['limit']:,}")
    print()
    print(f"burn rate      {u['burn_per_hour']:,} weighted tok/hour")
    print(f"headroom       {_fmt_hours(u['hours_left'])} of work left "
          f"(binding limit: {u['binding']})")
    print()
    print("Ceilings are estimates - Anthropic does not publish them in tokens.")
    print(f"Correct them with: {cli_invocation()} usage --window-tokens N --weekly-tokens N")


def cmd_status(args):
    root = find_root()
    s = collect_status(root)
    print(f"{s['name']}  [{s['track_label']}]")
    print(f"phase: {s['phase']}   spec: {'APPROVED' if s['approved'] else 'DRAFT'}"
          f"   review round: {s['review_round']}")
    print()
    for name, a in s["agents"].items():
        print(f"  {name:<8} {a['model']:<18} {a['calls']:>3} calls  "
              f"{a['tokens']:>9,} tok  {a['seconds']:>6.1f}s"
              f"{'  measured' if a.get('measured') else ''}")

    u = s.get("usage") or {}
    if u.get("available"):
        print()
        print(f"  budget   {u['window_hours']:g}h window {u['window']['percent']:.1f}% used, "
              f"week {u['week']['percent']:.1f}% used, "
              f"~{_fmt_hours(u['hours_left'])} left at {u['burn_per_hour']:,} tok/h")
    if s["tasks"] and not s["tasks"].get("error"):
        t = s["tasks"]
        print()
        print(f"roadmap: {t['done']}/{t['total']} done, {t['value_percent']}% by value"
              + (f", next {t['ready'][0]}" if t["ready"] else ""))

    pend = s["pending_questions"]
    print()
    print(f"pending questions: {len(pend)}")
    for q in pend[:5]:
        print(f"  - {q['text'][:90]}")


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def cmd_start(args):
    root = find_root()
    cfg = read_json(root / ORCH / "config.json")
    claude_model = cfg.get("agents", {}).get("claude", {}).get("model", "opus")

    lines = {
        "claude": f'claude --dangerously-skip-permissions --model {claude_model}',
        "gemini": "gemini",
        "codex": "codex --sandbox read-only",
    }

    which = args.agent
    if which == "all":
        print(f"Workspace: {root}\n")
        print("Claude is your driver. Gemini and Codex are usually called through")
        print("`syncagent.py ask` rather than opened directly - open them only when")
        print("you want to talk to one yourself.\n")
        for name, cmd in lines.items():
            missing = "" if have(name) else "   (not on PATH)"
            print(f"  {name:<8} {cmd}{missing}")
        print("\nIn Claude, start with:  /align <what you want>")
        print("Dashboard:              python syncagent.py dash")
        return

    cmd = lines[which]
    if not have(which):
        sys.exit(f"'{which}' is not on your PATH.")
    log_event(root, {"kind": "start", "agent": which})
    parts = cmd.split()
    parts[0] = exe(parts[0])
    if os.name == "nt":
        # execvp on Windows detaches oddly and loses the console; run as a child.
        sys.exit(subprocess.call(parts, cwd=root))
    os.chdir(root)
    os.execvp(parts[0], parts)


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

DASH_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SyncAgent</title>
<style>
  :root{
    --ground:#EDEFEA; --panel:#F6F7F3; --ink:#1B211E; --soft:#5C6660;
    --rule:#C7CDC3; --claude:#3B5E4A; --gemini:#2E5C8A; --codex:#7A6A2F;
    --alert:#A8392B;
    --mono:"JetBrains Mono","Cascadia Code","SF Mono",ui-monospace,Menlo,
           "DejaVu Sans Mono",Consolas,monospace;
    --serif:"Iowan Old Style","Source Serif 4",Charter,Georgia,
            "Times New Roman",serif;
  }
  @media (prefers-color-scheme:dark){
    :root{--ground:#141815;--panel:#1C211D;--ink:#E4E8E2;--soft:#8D968F;
          --rule:#333A35;--claude:#7FB394;--gemini:#7CA9D6;--codex:#C4B26A;
          --alert:#E0705E;}
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--mono);
       font-size:15px;line-height:1.6;padding:32px 26px 64px;
       -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;
       font-variant-numeric:tabular-nums}
  h1{font-family:var(--serif);font-weight:400;font-size:40px;margin:0;letter-spacing:-.015em}
  h2{font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.14em;
     text-transform:uppercase;color:var(--soft);margin:0 0 13px;
     border-bottom:1px solid var(--rule);padding-bottom:8px}
  .wrap{max-width:1280px;margin:0 auto}
  header{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;
         border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:24px}
  .sub{color:var(--soft);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  @media(max-width:860px){.grid{grid-template-columns:1fr}}
  .panel{background:var(--panel);border:1px solid var(--rule);padding:16px}
  .span2{grid-column:1/-1}

  /* phase rail */
  .rail{display:flex;gap:0;margin-bottom:22px;border:1px solid var(--rule)}
  .ph{flex:1;padding:11px 6px;text-align:center;font-size:11.5px;letter-spacing:.12em;
      text-transform:uppercase;color:var(--soft);border-right:1px solid var(--rule);
      background:var(--panel)}
  .ph:last-child{border-right:none}
  .ph.on{background:var(--ink);color:var(--ground);font-weight:600}
  .ph.done{color:var(--ink)}

  /* agent meters */
  .agent{margin-bottom:18px}
  .agent:last-child{margin-bottom:0}
  .arow{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
  .aname{font-weight:600;font-size:17px}
  .ameta{color:var(--soft);font-size:13px}
  .meter{display:flex;gap:2px;margin-top:8px;height:14px}
  .seg{flex:1;background:var(--rule);opacity:.45}
  .seg.lit{opacity:1}
  .c-claude .seg.lit{background:var(--claude)} .c-claude .aname{color:var(--claude)}
  .c-gemini .seg.lit{background:var(--gemini)} .c-gemini .aname{color:var(--gemini)}
  .c-codex  .seg.lit{background:var(--codex)}  .c-codex  .aname{color:var(--codex)}
  .anum{font-size:12.5px;color:var(--soft);margin-top:6px;display:flex;
        justify-content:space-between}

  /* liveness */
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
       background:var(--rule);margin-right:7px;vertical-align:middle}
  .s-live .dot{background:var(--claude);box-shadow:0 0 0 0 var(--claude);
               animation:pulse 1.8s infinite}
  .s-idle .dot{background:var(--codex)}
  .s-cold .dot{background:var(--rule)}
  .s-missing .dot,.s-never .dot{background:transparent;border:1px solid var(--rule)}
  .s-cold .aname,.s-missing .aname,.s-never .aname{opacity:.5}
  .s-missing .meter,.s-never .meter,.s-cold .meter{opacity:.4}
  @keyframes pulse{
    0%{box-shadow:0 0 0 0 rgba(127,179,148,.55)}
    70%{box-shadow:0 0 0 6px rgba(127,179,148,0)}
    100%{box-shadow:0 0 0 0 rgba(127,179,148,0)}}
  .state{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase}
  .s-live .state{color:var(--claude)}
  .s-idle .state{color:var(--codex)}

  /* budget */
  .budget{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
  @media(max-width:860px){.budget{grid-template-columns:1fr}}
  .big{font-family:var(--serif);font-size:36px;line-height:1.1;letter-spacing:-.02em}
  .cap{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--soft)}
  .warn .big{color:var(--alert)}
  .fine{font-size:12px;color:var(--soft);margin-top:12px;font-style:italic}

  /* roadmap */
  .road{margin-bottom:20px}
  .roadhead{display:flex;justify-content:space-between;align-items:baseline;
            margin-bottom:10px;font-size:13px;color:var(--soft)}
  .bar{display:flex;gap:2px;height:14px;margin-bottom:13px}
  .bar .seg{flex:1;background:var(--rule);opacity:.45}
  .bar .seg.lit{opacity:1;background:var(--ink)}
  .tk{display:flex;align-items:baseline;gap:9px;padding:4px 0;
      border-bottom:1px solid var(--rule)}
  .tk:last-child{border-bottom:none}
  .tk .mk{width:15px;color:var(--soft)}
  .tk .tid{width:50px;color:var(--soft);font-size:13px}
  .tk .ttl{flex:1}
  .tk.done{color:var(--soft)}
  .tk.done .ttl{text-decoration:line-through}
  .tk.doing .mk{color:var(--ink);font-weight:600}
  .tk.blocked .mk{color:var(--alert)}
  .tk.next .ttl{font-weight:600}
  .val{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--soft)}

  /* questions */
  .q{border-left:3px solid var(--alert);padding:7px 0 7px 11px;margin-bottom:9px}
  .q.ok{border-left-color:var(--rule);color:var(--soft)}
  .qcount{color:var(--alert);font-weight:600}
  .none{color:var(--soft);font-style:italic}

  /* files + tape */
  ul{list-style:none;margin:0;padding:0}
  li{padding:3px 0;border-bottom:1px solid var(--rule);display:flex;
     justify-content:space-between;gap:12px}
  li:last-child{border-bottom:none}
  .t{color:var(--soft);font-size:12.5px;white-space:nowrap}
  .scroll{max-height:290px;overflow-y:auto}
  .tag{display:inline-block;padding:1px 7px;font-size:11px;letter-spacing:.08em;
       text-transform:uppercase;border:1px solid currentColor;margin-right:7px}
  .g-claude{color:var(--claude)} .g-gemini{color:var(--gemini)} .g-codex{color:var(--codex)}
  pre{white-space:pre-wrap;font-family:var(--mono);font-size:14px;margin:0;
      color:var(--soft);max-height:250px;overflow-y:auto}
  .stamp{color:var(--soft);font-size:11.5px;letter-spacing:.1em;margin-top:26px;
         text-align:right;text-transform:uppercase}
  .flag{display:inline-block;padding:3px 9px;font-size:11.5px;letter-spacing:.1em;
        text-transform:uppercase;font-weight:600}
  .flag.draft{background:var(--alert);color:var(--ground)}
  .flag.appr{border:1px solid var(--rule);color:var(--soft)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="name">-</h1>
    <span class="sub" id="track"></span>
    <span id="specflag"></span>
  </header>

  <div class="rail" id="rail"></div>

  <div class="grid">
    <div class="panel span2" id="budgetpanel">
      <h2>Subscription budget <span class="qcount" id="budgetflag"></span></h2>
      <div id="budget"></div>
    </div>

    <div class="panel span2" id="roadpanel" style="display:none">
      <h2>Roadmap <span class="qcount" id="roadpct"></span></h2>
      <div class="road">
        <div class="roadhead"><span id="roadcount"></span><span id="roadnext"></span></div>
        <div class="bar" id="roadbar"></div>
        <div id="roadlist" class="scroll"></div>
      </div>
    </div>

    <div class="panel">
      <h2>Engines</h2>
      <div id="agents"></div>
    </div>

    <div class="panel">
      <h2>Waiting on you <span class="qcount" id="qn"></span></h2>
      <div id="questions" class="scroll"></div>
    </div>

    <div class="panel">
      <h2>Files created</h2>
      <ul id="made" class="scroll"></ul>
    </div>

    <div class="panel">
      <h2>Files fed in</h2>
      <ul id="fed" class="scroll"></ul>
    </div>

    <div class="panel span2">
      <h2>Run tape</h2>
      <ul id="tape" class="scroll"></ul>
    </div>

    <div class="panel span2">
      <h2>Status note</h2>
      <pre id="statusmd"></pre>
    </div>
  </div>
  <div class="stamp" id="stamp"></div>
</div>

<script>
const SEGS = 24;
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const clock = ts => ts ? new Date(ts).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '-';

function ago(seconds){
  if (seconds === null || seconds === undefined) return 'never';
  if (seconds < 60) return seconds + 's ago';
  if (seconds < 3600) return Math.round(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.round(seconds / 3600) + 'h ago';
  return Math.round(seconds / 86400) + 'd ago';
}

function fmtHours(h){
  if (h === null || h === undefined) return '--';
  if (h >= 24) return Math.floor(h / 24) + 'd ' + Math.round(h % 24) + 'h';
  const mins = Math.round(h * 60);
  return mins >= 60 ? Math.floor(mins / 60) + 'h ' + String(mins % 60).padStart(2, '0') + 'm'
                    : mins + 'm';
}

function meter(used, budget){
  const frac = budget > 0 ? Math.min(used / budget, 1) : 0;
  const lit = Math.round(frac * SEGS);
  let out = '';
  for (let i = 0; i < SEGS; i++) out += `<div class="seg${i < lit ? ' lit' : ''}"></div>`;
  return out;
}

async function tick(){
  let d;
  try { d = await (await fetch('/api/state')).json(); }
  catch { document.getElementById('stamp').textContent = 'connection lost'; return; }

  document.getElementById('name').textContent = d.name;
  document.getElementById('track').textContent = d.track_label;
  document.getElementById('specflag').innerHTML = d.approved
    ? '<span class="flag appr">spec approved</span>'
    : '<span class="flag draft">spec is draft &mdash; nothing may build</span>';

  const at = d.gates.indexOf(d.phase);
  document.getElementById('rail').innerHTML = d.gates.map((g, i) =>
    `<div class="ph ${i === at ? 'on' : (i < at ? 'done' : '')}">${esc(g)}${
      g === 'review' && d.review_round ? ' ' + d.review_round : ''}</div>`).join('');

  const STATE_LABEL = {live:'live', idle:'idle', cold:'not running',
                       missing:'not installed', never:'never used'};
  document.getElementById('agents').innerHTML = Object.entries(d.agents).map(([n, a]) => `
    <div class="agent c-${n} s-${esc(a.state || 'never')}">
      <div class="arow">
        <span class="aname"><span class="dot"></span>${esc(n)}</span>
        <span class="state">${STATE_LABEL[a.state] || ''}${
          a.state === 'idle' || a.state === 'cold' ? ' &middot; ' + ago(a.idle_seconds) : ''}</span>
      </div>
      <div class="ameta">${esc(a.model)} &middot; effort ${esc(a.effort)} &middot; ${esc(a.role)}</div>
      <div class="meter">${meter(a.tokens, a.budget)}</div>
      <div class="anum">
        <span>${a.calls} calls &middot; ${a.seconds}s &middot; ${
          a.measured ? 'measured' : 'self-reported'}</span>
        <span>${a.tokens.toLocaleString()} / ${a.budget.toLocaleString()} tok today</span>
      </div>
    </div>`).join('');

  const u = d.usage || {};
  const bflag = document.getElementById('budgetflag');
  if (!u.available) {
    bflag.textContent = '';
    document.getElementById('budget').innerHTML =
      `<div class="none">${esc(u.reason || 'No measured Claude usage yet.')}</div>`;
  } else {
    const w = u.window, k = u.week, s = u.session;
    const tight = w.percent >= 80 || k.percent >= 80;
    bflag.textContent = tight ? 'running low' : '';
    document.getElementById('budget').innerHTML = `
      <div class="budget">
        <div class="${tight ? 'warn' : ''}">
          <div class="cap">${u.window_hours}h window &middot; resets in ${
            fmtHours(w.resets_in_hours)}</div>
          <div class="big">${w.percent.toFixed(1)}%</div>
          <div class="meter">${meter(w.weighted, w.limit)}</div>
          <div class="anum"><span>${w.weighted.toLocaleString()} used</span>
            <span>${w.limit.toLocaleString()} cap</span></div>
        </div>
        <div class="${k.percent >= 80 ? 'warn' : ''}">
          <div class="cap">this week</div>
          <div class="big">${k.percent.toFixed(1)}%</div>
          <div class="meter">${meter(k.weighted, k.limit)}</div>
          <div class="anum"><span>${k.weighted.toLocaleString()} used</span>
            <span>${k.limit.toLocaleString()} cap</span></div>
        </div>
        <div>
          <div class="cap">headroom at ${u.burn_per_hour.toLocaleString()} tok/h</div>
          <div class="big">${fmtHours(u.hours_left)}</div>
          <div class="anum"><span>binding: ${esc(u.binding)} limit</span></div>
          <div class="anum"><span>session: ${s.calls} calls &middot; ${
            s.weighted.toLocaleString()} weighted</span></div>
          <div class="anum"><span>raw ${s.total.toLocaleString()} tok &middot; cache read ${
            s.cache_read.toLocaleString()}</span></div>
        </div>
      </div>
      <div class="fine">Weighted tokens: output &times;${u.weights.output}, cache write &times;${
        u.weights.cache_write}, cache read &times;${u.weights.cache_read}. Plan ${esc(u.plan)}
        ceilings are estimates &mdash; correct them with
        <code>usage --window-tokens N --weekly-tokens N</code>.</div>`;
  }

  const road = document.getElementById('roadpanel');
  const GLYPH = {todo:'·', doing:'›', done:'×', blocked:'!'};
  if (!d.tasks) {
    road.style.display = 'none';
  } else if (d.tasks.error) {
    road.style.display = '';
    document.getElementById('roadpct').textContent = '';
    document.getElementById('roadcount').textContent = d.tasks.error;
    document.getElementById('roadbar').innerHTML = '';
    document.getElementById('roadlist').innerHTML = '';
  } else {
    road.style.display = '';
    const t = d.tasks, nextId = t.ready.length ? t.ready[0] : null;
    document.getElementById('roadpct').textContent = t.value_percent + '%';
    document.getElementById('roadcount').textContent =
      `${t.done} of ${t.total} done · ${t.value_percent}% by value`;
    document.getElementById('roadnext').textContent = nextId ? 'next: ' + nextId : '';
    document.getElementById('roadbar').innerHTML =
      Array.from({length: SEGS}, (_, i) =>
        `<div class="seg${i < Math.round(t.value_percent / 100 * SEGS) ? ' lit' : ''}"></div>`).join('');
    document.getElementById('roadlist').innerHTML = t.tasks.length
      ? t.tasks.map(k => `<div class="tk ${esc(k.status || 'todo')}${
            k.id === nextId ? ' next' : ''}">
          <span class="mk">${GLYPH[k.status] || '·'}</span>
          <span class="tid">${esc(k.id || '')}</span>
          <span class="ttl">${esc(k.title || '')}</span>
          <span class="val">${esc(k.value || '')} ${esc(k.size || '')}</span>
          <span class="tag g-${esc(k.assignee || 'claude')}">${esc(k.assignee || 'claude')}</span>
        </div>`).join('')
      : '<div class="none">The roadmap is empty.</div>';
  }

  const pend = d.questions.filter(q => !q.answered);
  document.getElementById('qn').textContent = pend.length ? `(${pend.length})` : '';
  document.getElementById('questions').innerHTML = d.questions.length
    ? d.questions.map(q => `<div class="q ${q.answered ? 'ok' : ''}">${esc(q.text)}</div>`).join('')
    : '<div class="none">No questions outstanding.</div>';

  const list = (el, items, empty) => {
    document.getElementById(el).innerHTML = items.length
      ? items.map(f => `<li><span>${esc(f.path)}</span><span class="t">${clock(f.mtime)}</span></li>`).join('')
      : `<li><span class="none">${empty}</span></li>`;
  };
  list('made', d.files_made, 'Nothing written this session.');
  list('fed', d.files_fed, 'Nothing linked in. Use: syncagent.py ref <path>');

  document.getElementById('tape').innerHTML = d.events.length
    ? d.events.map(e => `<li><span><span class="tag g-${esc(e.agent || 'claude')}">${
        esc(e.agent || e.kind)}</span>${esc(e.role || e.phase || e.kind)}${
        e.tokens_total ? ' &middot; ' + e.tokens_total.toLocaleString() + ' tok' : ''}${
        e.ok === false ? ' &middot; FAILED' : ''}</span><span class="t">${clock(e.ts)}</span></li>`).join('')
    : '<li><span class="none">No runs yet.</span></li>';

  document.getElementById('statusmd').textContent = d.status_md || 'STATUS.md is empty.';
  document.getElementById('stamp').textContent = 'refreshed ' + new Date().toLocaleTimeString();
}
tick(); setInterval(tick, 2000);
</script>
</body>
</html>
"""


def cmd_dash(args):
    root = find_root()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/api/state"):
                self._send(json.dumps(collect_status(root)), "application/json")
            elif self.path in ("/", "/index.html"):
                self._send(DASH_HTML, "text/html; charset=utf-8")
            else:
                self.send_error(404)

    class DashServer(socketserver.ThreadingTCPServer):
        # must be a CLASS attribute: TCPServer.__init__ binds immediately, so
        # setting this on the instance afterwards is a no-op.
        allow_reuse_address = True
        daemon_threads = True

    with DashServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"SyncAgent dashboard -> http://127.0.0.1:{args.port}")
        print("ctrl-c to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="syncagent", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a workspace")
    p.add_argument("path")
    p.add_argument("--track", choices=sorted(TRACKS), default="code")
    p.add_argument("--name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("start", help="launch or list the CLIs")
    p.add_argument("agent", nargs="?", default="all",
                   choices=["all", "claude", "gemini", "codex"])
    p.set_defaults(func=cmd_start)

    p = sub.add_parser("ask", help="run a consultant agent headless")
    p.add_argument("agent", choices=["gemini", "codex"])
    p.add_argument("--role", required=True,
                   choices=["align", "research", "review", "tiebreak"])
    p.add_argument("--text", default="")
    p.add_argument("--show", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("ref", help="link outside material in read-only")
    p.add_argument("path")
    p.add_argument("--rename")
    p.add_argument("--copy", action="store_true")
    p.set_defaults(func=cmd_ref)

    p = sub.add_parser("gate", help="advance the phase")
    p.add_argument("phase")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("log", help="record Claude's own work (self-reported)")
    p.add_argument("--role", default="build")
    p.add_argument("--tokens", type=int, default=0)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("tasks", help="the roadmap ledger")
    tsub = p.add_subparsers(dest="tasks_cmd", required=True)

    q = tsub.add_parser("validate", help="schema, unknown ids, duplicates, cycles")
    q.set_defaults(func=cmd_tasks_validate)

    q = tsub.add_parser("next", help="the single next task, as JSON")
    q.set_defaults(func=cmd_tasks_next)

    q = tsub.add_parser("parallel", help="a batch with provably disjoint files")
    q.add_argument("--max", type=int, default=3)
    q.set_defaults(func=cmd_tasks_parallel)

    q = tsub.add_parser("start", help="mark a task in progress")
    q.add_argument("id")
    q.add_argument("--force", action="store_true", help="start despite unmet dependencies")
    q.set_defaults(func=cmd_tasks_start)

    q = tsub.add_parser("done", help="mark done and commit the checkpoint")
    q.add_argument("id")
    q.add_argument("--no-commit", action="store_true")
    q.set_defaults(func=cmd_tasks_done)

    q = tsub.add_parser("block", help="mark blocked with a reason")
    q.add_argument("id")
    q.add_argument("--reason", required=True)
    q.set_defaults(func=cmd_tasks_block)

    q = tsub.add_parser("list", help="the roadmap as a table")
    q.set_defaults(func=cmd_tasks_list)

    p = sub.add_parser("resume", help="pick up an interrupted session cheaply")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("status", help="text summary")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("usage", help="measured token spend and subscription headroom")
    p.add_argument("--json", action="store_true")
    p.add_argument("--plan", choices=sorted(PLAN_LIMITS),
                   help="apply a plan preset to the ceilings")
    p.add_argument("--window-tokens", type=int,
                   help="correct the rolling-window ceiling (weighted tokens)")
    p.add_argument("--weekly-tokens", type=int,
                   help="correct the weekly ceiling (weighted tokens)")
    p.set_defaults(func=cmd_usage)

    p = sub.add_parser("dash", help="web dashboard")
    p.add_argument("--port", type=int, default=7777)
    p.set_defaults(func=cmd_dash)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
