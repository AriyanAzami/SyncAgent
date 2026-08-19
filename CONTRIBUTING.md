# Contributing

Issues and pull requests are welcome.

## The two real rules

**Standard library only.** No `requirements.txt`, no `pyproject.toml`, no vendored
packages. You clone SyncAgent and run it on any machine with Python — that property is
most of its value.

**Keep it small.** SyncAgent 2.x was a package, a relay, a web server and a dashboard —
about 3,600 lines to do what a folder of markdown and one script now does. The
orchestration lives in Claude Code because Claude Code is already an orchestrator. If a
change adds a second executable, a config format, or a process that stays running, it is
probably the beginning of that regrowth.

There are two kinds of file here and they take different care:

| | |
|---|---|
| `ask.py` | the only code. Runs one CLI read-only, writes its answer to a file. |
| `.claude/skills/*/SKILL.md` | behaviour. What Claude Code actually does, in English. |
| `CLAUDE.md` | loaded every session, so every line has to earn its place. |

## Changing a skill

The skills are the product. Prose there is not documentation — it is the instruction
Claude Code follows, so vagueness is a bug.

- Say what to do, not what to consider. "Ask a second advisor when the work is heavy on
  reasoning that can be flatly right or wrong" beats "consider multiple perspectives".
- Keep the trigger conditions in the frontmatter `description` concrete. That sentence is
  the whole basis on which the skill gets loaded.
- If you change one, say in the PR what went wrong without the change. A skill edit that
  cannot point at a bad run is a preference.

Adding a domain skill — `cover-letter`, `grant-application`, `thesis` — is the most
useful contribution there is, and the least risky. Copy `resume`, change the bar.

## Changing ask.py

Target Python 3.8, and keep it working on macOS, Linux and Windows. There is no test
suite — the file is 300 lines and every path is one command away:

```bash
python ask.py doctor
python ask.py new smoke
python ask.py codex smoke -m "reply with the word ok, nothing else"
```

Two portability traps, both handled — please don't reintroduce them:

- Launch CLIs through `exe()`, never a bare name. On Windows several are npm shims
  (`gemini.CMD`), which `shutil.which` finds but `CreateProcess` will not run.
- Prompts go over **stdin** wherever the CLI allows it. `agy` is the exception — it takes
  the prompt as an argv value and ignores stdin — which is why that adapter caps the
  prompt at 28,000 characters instead.

## Things that look arbitrary and are not

Each of these replaced a specific failure. Please don't relax one without saying in the
PR what got worse when you tried.

- **Advisors run read-only.** Not a politeness. Two agents editing the same file is the
  exact failure this design avoids, so it is made impossible rather than discouraged.
- **The prompt lists every file by absolute path.** Antigravity's file tool rejects
  relative paths outright, and glob-style discovery quietly honours `.gitignore` — so an
  advisor asked to "look in input/" reports that the user's material does not exist and
  reviews nothing. Listing beats discovery.
- **Non-text files are marked `[not plain text]`.** Handed a PDF, an advisor will write a
  full report about material it never opened. Saying so up front makes it report the gap
  instead of hallucinating around it.
- **The structured error event wins over the last line of stderr.** Codex logs unrelated
  warnings to stderr while reporting a quota refusal as a JSON event on stdout; the naive
  version blamed a stray plugin warning for the failure.
- **A failed call still writes a note file.** The failure is part of the record, and a
  silent one sends the next round looking for a file that is not there.
- **`doctor` makes a real call.** A CLI can be on PATH, logged in, and still unable to
  answer — Gemini's withdrawn free tier is exactly this. Only a real call distinguishes
  "installed" from "works".
- **Antigravity's read-only mode is `--sandbox`, not `--mode plan`.** plan mode refuses
  every tool, so an advisor cannot even open `input/` and returns an empty response. The
  sandbox reads fine and silently drops writes — checked by hand, because it is a
  security claim.
- **Quality control judges against `GOAL.md`, not against the feedback.** Work can absorb
  every note an advisor gave and still miss the goal. That is the failure the gate exists
  to catch, and the reason the bar is written before the work starts.

## Scope

Good fits: new domain skills, sharper prose in the existing ones, a new advisor CLI,
better parsing as these CLIs change their output, Windows/macOS/Linux portability.

Poor fits: a plugin system, a config framework, a web UI, an agent-framework dependency,
a scheduler, or asking every model the same question and averaging them — that last one
is the thing this tool is deliberately not.
