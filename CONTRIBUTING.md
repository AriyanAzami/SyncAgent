# Contributing

Issues and pull requests are welcome.

## The one real rule

**Standard library only.** No `requirements.txt`, no `pyproject.toml`, no vendored
packages. You clone SyncAgent and run it, on any machine with Python — that property is
most of its value. If a change needs a dependency, it probably belongs in your own fork.

SyncAgent 1.x was a single 2,500-line `syncagent.py`, and that file being one file was
listed here as a rule. It is not any more: it grew past the point where anyone could find
anything in it, which was a large part of why people struggled to understand the tool.
The code is now a package, and cloning-and-running is unchanged. Keep modules focused:

| File | Holds |
|---|---|
| `sync.py` | the entry point, and nothing else |
| `syncagent/table.py` | the folder model — topics, briefs, handoff parsing, depth slicing |
| `syncagent/seats.py` | the CLI adapters, and every quirk of their flags and JSON |
| `syncagent/runner.py` | the single-worker relay |
| `syncagent/usage.py` | measured Claude spend |
| `syncagent/server.py` | dashboard HTTP and API |
| `syncagent/ui.py` | the page |
| `syncagent/prompts.py` | the turn templates |

CLI-specific weirdness belongs in `seats.py`. Nothing above that file should know that
Gemini calls it `--approval-mode` and Codex calls it `--sandbox`.

## Before you open a PR

Target Python 3.8, and keep it working on macOS, Linux, and Windows.

```bash
python -m unittest discover -s tests
```

The suite launches no CLIs — every seat is faked — so it runs on a machine with none of
the three installed. Then the smoke sequence:

```bash
python sync.py setup --path /tmp/sa-check
cd /tmp/sa-check
python sync.py doctor
python sync.py ask "sanity check: reply briefly" --seat claude
python sync.py dash --port 7799 --no-browser
```

Two portability traps, both already handled — please don't reintroduce them:

- Launch CLIs through `exe()`, never a bare name. On Windows the three CLIs are npm
  shims (`gemini.CMD`), which `shutil.which` finds but `CreateProcess` will not run.
- Prompts go over **stdin**, never argv. A brief plus prior turns will exceed `ARG_MAX`
  eventually, and that failure looks like an unrelated crash.

## Things that look arbitrary and are not

Each of these replaced a specific failure. Please don't relax one without saying in the
PR what got worse when you tried.

- **One worker thread.** Not a performance choice. Concurrent seats re-establishing the
  same context is the exact failure this tool exists to avoid, so it is made impossible
  rather than discouraged.
- **Depth trims bytes, not just wording.** A seat told to be brief but handed everything
  will not be brief. `prior_turns()` is where this is enforced.
- **`rule_first` exists.** A `light` seat told "someone already did the deep pass" when it
  is running first will either invent that pass or argue with the prompt. Observed in a
  real run, not theorised.
- **Topic numbers come from a persisted counter, not a folder count.** Delete topic 002
  and a count hands 002 straight back out, so two topics collide in filenames and
  telemetry.
- **Step order is list position, not the `n` field.** `n` is a stable id that ends up in
  filenames; an inserted detour has a high `n` but must run next.
- **`doctor` makes a real call.** A seat can be on PATH, logged in, and still unable to
  answer — Gemini's withdrawn free tier is exactly this. Only a real call distinguishes
  "installed" from "works".
- **The turn file is written before the handoff is parsed.** A turn that produced work
  must leave it on disk even if the handoff is malformed.

## Changing prompts

`syncagent/prompts.py` is behaviour, not documentation, and `table/prompts/turn.md`
overrides it per table. If you change one, say in the PR what got worse without it.

## Scope

Good fits: bugs, Windows/macOS/Linux portability, better parsing of the CLIs' JSON output
as they change, dashboard clarity, new lenses.

Poor fits: a plugin system, a config framework, a hosted web UI, an agent framework
dependency, or symmetric broadcast-to-all-models — that last one is the thing this tool
is deliberately not.
