#!/usr/bin/env python3
"""Hand a job to another AI CLI and land its answer on the table as markdown.

This is the only executable in SyncAgent, and it does one thing: run a
different vendor's coding CLI in read-only mode, pointed at a job folder, and
write whatever it says into `table/<job>/notes/`. Claude Code reads that file
and does the actual work.

    python ask.py doctor                 which CLIs on this machine can answer
    python ask.py new resume-2027        make a job folder
    python ask.py codex resume-2027      get Codex's read on it
    python ask.py gemini resume-2027 -m "focus on the summary section"

The advisors are deliberately read-only. They cannot edit your files, and
nothing they say is applied automatically - their report is an opinion sitting
in a file until Claude Code decides what to do with it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TABLE = ROOT / "table"
TIMEOUT = 900


# ---------------------------------------------------------------------------
# finding the CLIs
# ---------------------------------------------------------------------------

# Where a CLI installs itself when it does not put itself on PATH. Antigravity
# is the current example: it ships an `agy install` subcommand that edits your
# shell profile, so a fully working install is invisible to `which` until you
# run that and open a new terminal.
EXTRA_BIN_DIRS = {
    "agy": [
        Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin",
        Path.home() / ".agy" / "bin",
        Path.home() / ".local" / "bin",
        Path("/usr/local/bin"),
    ],
}


def find_binary(name):
    """Full path to a CLI, or None. PATH first, then the known homes."""
    found = shutil.which(name)
    if found:
        return found
    for d in EXTRA_BIN_DIRS.get(name, []):
        try:
            for candidate in (d / name, d / f"{name}.exe", d / f"{name}.cmd"):
                if candidate.is_file():
                    return str(candidate)
        except OSError:
            continue
    return None


def exe(name):
    """Resolve a CLI to a full path before launching it.

    On Windows several of these are npm shims - `gemini.CMD`, not
    `gemini.exe`. shutil.which() finds them because it honours PATHEXT, but
    CreateProcess only ever appends `.exe` when it searches PATH, so passing
    the bare name to subprocess fails on a machine where the CLI plainly works.
    """
    return find_binary(name) or name


def run(cmd, stdin=""):
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), input=stdin, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "", f"timed out after {TIMEOUT}s", 1
    except OSError as e:
        return "", f"could not start {cmd[0]}: {e}", 1
    return proc.stdout or "", proc.stderr or "", proc.returncode


# All of these CLIs report "you are not signed in" as an ordinary run that
# produced no answer. Naming the failure is the difference between "Gemini
# needs an API key" and an empty file you have to guess about.
AUTH_HINTS = (
    (r"IneligibleTierError|no longer supported for Gemini Code Assist",
     "Gemini's free CLI tier is withdrawn for individual accounts. Set "
     "GEMINI_API_KEY (aistudio.google.com/apikey) or GOOGLE_CLOUD_PROJECT."),
    (r"Error authenticating|not authenticated|please (re)?login|"
     r"run [`']?(gemini|codex|claude) login",
     "Installed but not signed in. Run the CLI once by hand and finish its login."),
    (r"invalid[_ ]api[_ ]key|401 Unauthorized|403 Forbidden",
     "Credentials rejected. Check the API key or re-run the CLI's login."),
    (r"quota|rate.?limit|429|resource[_ ]exhausted",
     "Out of quota right now. Ask a different advisor, or wait."),
)


def diagnose(*blobs):
    blob = "\n".join(b or "" for b in blobs)
    for pattern, message in AUTH_HINTS:
        if re.search(pattern, blob, re.I):
            return message
    return ""


def fail(out, err, code):
    hint = diagnose(err, out)
    if hint:
        return hint
    tail = (err or out or "").strip().splitlines()
    return tail[-1][:300] if tail else f"exit {code}"


# ---------------------------------------------------------------------------
# the advisors
# ---------------------------------------------------------------------------
#
# One function per CLI. They disagree about flags, about output format, and
# about how you ask for read-only, so the disagreement is quarantined here and
# nothing else in the project knows about it. Each returns (text, error).


def ask_codex(prompt, model):
    cmd = [exe("codex"), "exec", "-", "--json", "--skip-git-repo-check",
           "--sandbox", "read-only", "--ephemeral"]
    if model:
        cmd += ["--model", model]
    out, err, code = run(cmd, prompt)

    # Codex reports why it stopped as an `error` / `turn.failed` event on
    # stdout, and separately logs unrelated warnings to stderr. Taking the last
    # stderr line would blame a stray plugin warning for a quota refusal, so the
    # structured event wins whenever there is one.
    parts, reported = [], ""
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") in ("error", "turn.failed"):
            message = event.get("message") or (event.get("error") or {}).get("message")
            if message:
                reported = str(message).strip()
        item = event.get("item") or {}
        if item.get("type") in ("agent_message", "assistant_message"):
            text = item.get("text") or item.get("content") or ""
            if isinstance(text, str) and text.strip():
                parts.append(text)

    answer = "\n".join(parts).strip()
    if answer:
        return answer, ""
    return "", (reported[:400] or fail(out, err, code))


def ask_gemini(prompt, model):
    # `plan` is Gemini CLI's real read-only mode, so an advisor is prevented
    # from writing rather than merely asked not to.
    cmd = [exe("gemini"), "-o", "json", "--approval-mode", "plan"]
    if model:
        cmd += ["-m", model]
    out, err, code = run(cmd, prompt)

    reported = ""
    try:
        data = json.loads(strip_fences(out))
    except json.JSONDecodeError:
        answer = out.strip()
    else:
        answer = (data.get("response") or "").strip() if isinstance(data, dict) else ""
        problem = data.get("error") if isinstance(data, dict) else None
        if isinstance(problem, dict):
            reported = str(problem.get("message") or "").strip()
        elif isinstance(problem, str):
            reported = problem.strip()

    if answer and code == 0:
        return answer, ""
    return "", (diagnose(reported) or reported[:400] or fail(out, err, code))


# `agy -p` takes the prompt as the flag's *value* and ignores stdin. That puts
# the whole prompt on the command line, and Windows caps a command line at
# 32,767 characters, so a long GOAL.md would fail as an unrelated-looking
# crash. Truncating deliberately, with a visible marker, is the honest version.
AGY_CAP = 28_000


def ask_antigravity(prompt, model):
    if len(prompt) > AGY_CAP:
        prompt = prompt[:AGY_CAP] + f"\n\n[truncated at {AGY_CAP:,} characters]"

    # Read-only here is `--sandbox`, not `--mode plan`. plan mode refuses every
    # tool, so the advisor cannot even open the files in input/ and returns an
    # empty answer. The skip-permissions flag is required alongside it because
    # headless mode cannot show an approval prompt; the sandbox, not the
    # prompt, is what contains this seat.
    cmd = [exe("agy"), "--output-format", "json", "--dangerously-skip-permissions",
           "--sandbox"]
    if model:
        cmd += ["--model", model]
    cmd += ["--print-timeout", f"{TIMEOUT}s", "-p", prompt]  # -p must stay last
    out, err, code = run(cmd)

    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and '"conversation_id"' in line:
            try:
                answer = (json.loads(line).get("response") or "").strip()
            except json.JSONDecodeError:
                continue
            if answer:
                return answer, ""
            return "", (diagnose(err, out) or "Antigravity returned nothing - it "
                        "reports success with an empty response when a tool it "
                        "reached for was denied.")
    return "", fail(out, err, code)


def ask_claude(prompt, model):
    """A second Claude, for when you want a fresh pair of eyes from the same
    vendor. `dontAsk` denies anything outside the read-only command set."""
    cmd = [exe("claude"), "-p", "--output-format", "json",
           "--permission-mode", "dontAsk"]
    if model:
        cmd += ["--model", model]
    out, err, code = run(cmd, prompt)

    try:
        data = json.loads(out.strip() or "{}")
    except json.JSONDecodeError:
        answer = out.strip() if code == 0 else ""
    else:
        answer = "" if data.get("is_error") else (data.get("result") or "").strip()
    return (answer, "") if answer else ("", fail(out, err, code))


ADVISORS = {
    "codex":       {"bin": "codex",  "run": ask_codex,       "model": ""},
    "gemini":      {"bin": "gemini", "run": ask_gemini,      "model": ""},
    "antigravity": {"bin": "agy",    "run": ask_antigravity, "model": ""},
    "claude":      {"bin": "claude", "run": ask_claude,      "model": ""},
}


# ---------------------------------------------------------------------------
# the table
# ---------------------------------------------------------------------------

GOAL_TEMPLATE = """# Goal

<!-- Claude Code writes this. One job, one goal. -->

## What we are making

## What "good" means
<!-- The bar quality control will hold this to. Be specific enough that an
     outside reader could judge the work against it without asking you. -->

## Material
<!-- Which files in input/ matter, and what they are. -->

## Constraints
<!-- Length, format, tone, deadline, anything that is not negotiable. -->
"""

STATUS_TEMPLATE = """# Status

**Round:** 0
**State:** open

## Log
<!-- Newest entry at the bottom. One line per thing that actually happened. -->
"""


def slugify(text, limit=40):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] or s[:limit]
    return s or "job"


def strip_fences(text):
    """Models wrap output in ``` fences even when told not to."""
    t = (text or "").strip()
    m = re.match(r"^```[A-Za-z0-9_+-]*\s*\n(.*?)\n?```$", t, re.S)
    return m.group(1).strip() if m else t


def job_dir(name):
    return TABLE / slugify(name)


def read(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return default


def next_note(notes, agent):
    n = len(list(notes.glob("*.md"))) + 1
    return notes / f"{n:02d}-{agent}.md"


# Text these advisors can actually read. A PDF or a .docx handed to a CLI comes
# back as binary noise or an unhelpful refusal, so the manifest marks them
# rather than letting the advisor discover it halfway through a round.
TEXTUAL = {".md", ".txt", ".markdown", ".rst", ".csv", ".tsv", ".json", ".yaml",
           ".yml", ".html", ".xml", ".tex", ".py", ".js", ".ts", ".sh", ".sql"}


def manifest(folder):
    """Every file in a folder, as absolute paths.

    Absolute, because the advisors do not agree on what a relative path means -
    Antigravity's file tool rejects them outright. Listed rather than left to be
    discovered, because a glob that quietly honours .gitignore is how an advisor
    concludes the user's material does not exist.
    """
    if not folder.is_dir():
        return "  (folder does not exist)"
    files = sorted(p for p in folder.rglob("*")
                   if p.is_file() and p.name != "README.md")
    if not files:
        return "  (empty)"
    lines = []
    for p in files:
        note = "" if p.suffix.lower() in TEXTUAL else "   [not plain text]"
        lines.append(f"  {p}{note}")
    return "\n".join(lines)


def build_prompt(job, agent, extra):
    goal = read(job / "GOAL.md", "(no GOAL.md yet)")
    status = read(job / "STATUS.md", "(no STATUS.md yet)")

    notes = sorted((job / "notes").glob("*.md"))
    prior = ("\n".join(f"  {p}" for p in notes)
             if notes else "  (none yet - you are the first)")

    return f"""You are giving an outside opinion on a piece of work. You are a
critic, not an editor. You cannot change any file, and nothing you write is
applied directly - Claude Code reads your report and decides what to do with it.

Use absolute paths when you open anything. Here is everything on the table.

The user's source material:
{manifest(ROOT / "input")}

The current draft:
{manifest(ROOT / "output")}

Text pulled out of that material for you, where it needed converting:
{manifest(job / "material")}

This job:
  {job / "GOAL.md"}     what we are making and what "good" means
  {job / "STATUS.md"}   what has happened so far

Earlier reports on this job, worth reading so you do not repeat them:
{prior}

Anything marked `[not plain text]` will not open usefully. If you need what is
inside one, say so in your report - Claude Code can convert it - and judge what
you can see in the meantime rather than stopping.

--- GOAL.md ---
{goal}

--- STATUS.md ---
{status}
--- end ---

{extra or "Give your honest read on where this work stands against the goal."}

Answer in markdown. Be concrete: quote the line you mean, say what is wrong
with it, and say what would be better instead. Order your points by how much
they actually matter - three real problems beat twelve observations. If
something is already good, say so in one line and move on. Do not restate the
goal back to us.

Finish with a section titled `## Verdict` that says, in two or three sentences,
whether the work meets the goal as it stands and what the single most important
next change is."""


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_doctor(args):
    print()
    prompt = "Reply with exactly the word: ok"
    for name, spec in ADVISORS.items():
        if not find_binary(spec["bin"]):
            print(f"  {name:<12} missing    '{spec['bin']}' is not on your PATH")
            continue
        started = time.time()
        text, err = spec["run"](prompt, spec["model"])
        secs = time.time() - started
        if err:
            print(f"  {name:<12} blocked    {err}")
        else:
            print(f"  {name:<12} ready      answered in {secs:.1f}s")
    print()
    return 0


def cmd_new(args):
    job = job_dir(args.job)
    for folder in ("notes", "material"):
        (job / folder).mkdir(parents=True, exist_ok=True)
    for filename, template in (("GOAL.md", GOAL_TEMPLATE),
                               ("STATUS.md", STATUS_TEMPLATE)):
        path = job / filename
        if not path.exists():
            path.write_text(template, encoding="utf-8")
    print(job.relative_to(ROOT).as_posix())
    return 0


def cmd_ask(args):
    spec = ADVISORS[args.agent]
    job = job_dir(args.job)
    if not job.is_dir():
        print(f"no such job: {job.relative_to(ROOT).as_posix()} "
              f"(make it with: python ask.py new {args.job})", file=sys.stderr)
        return 1
    if not find_binary(spec["bin"]):
        print(f"'{spec['bin']}' is not on your PATH", file=sys.stderr)
        return 1

    notes = job / "notes"
    notes.mkdir(exist_ok=True)
    (job / "material").mkdir(exist_ok=True)
    prompt = build_prompt(job, args.agent, args.message)

    started = time.time()
    text, err = spec["run"](prompt, args.model or spec["model"])
    secs = time.time() - started

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    path = next_note(notes, args.agent)
    if err:
        body = f"# {args.agent} — failed\n\n*{stamp}*\n\n{err}\n"
        path.write_text(body, encoding="utf-8")
        print(path.relative_to(ROOT).as_posix(), file=sys.stdout)
        print(f"{args.agent} failed: {err}", file=sys.stderr)
        return 1

    header = f"# {args.agent}\n\n*{stamp} · {secs:.0f}s*"
    if args.message:
        header += f"\n\n**Asked:** {args.message}"
    path.write_text(f"{header}\n\n---\n\n{strip_fences(text)}\n", encoding="utf-8")
    print(path.relative_to(ROOT).as_posix())
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ask.py", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="which advisors on this machine can answer")

    new = sub.add_parser("new", help="make a job folder on the table")
    new.add_argument("job")

    for name in ADVISORS:
        p = sub.add_parser(name, help=f"ask {name} for its read on a job")
        p.add_argument("job")
        p.add_argument("-m", "--message", default="",
                       help="what you specifically want it to look at")
        p.add_argument("--model", default="", help="override the model")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "new":
        return cmd_new(args)
    args.agent = args.command
    return cmd_ask(args)


if __name__ == "__main__":
    sys.exit(main())
