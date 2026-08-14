<div align="center">

# SyncAgent

**Claude Code, Gemini CLI, and Codex CLI working on one task, coordinated through
markdown files in a single folder — with a local dashboard showing what each one is
doing and what it is costing.**

Made by **[Ariyan Azami](https://github.com/AriyanAzami)**

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-1B211E?style=flat-square)](https://www.python.org/downloads/)
[![Dependencies: none](https://img.shields.io/badge/dependencies-none-3B5E4A?style=flat-square)](#requirements)
[![Platforms](https://img.shields.io/badge/macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-supported-2E5C8A?style=flat-square)](#install)
[![License: MIT](https://img.shields.io/badge/license-MIT-7A6A2F?style=flat-square)](LICENSE)

</div>

<!-- TODO(owner): capture the dashboard at 127.0.0.1:7777 mid-run and save it as docs/dashboard.png -->
![dashboard](docs/dashboard.png)

---

## The problem

If you pay for more than one AI subscription, you end up copy-pasting between terminals:
the spec into one, the diff into another, the review comments back into the first. The
obvious fix is to let the agents talk to each other, and that usually makes it worse.
Symmetric multi-agent setups spend most of their tokens re-establishing context and
agreeing with one another, and you get a transcript instead of an answer.

SyncAgent goes the other way. One agent drives and holds the context. The other two are
called as stateless one-shot subprocesses that see a frozen spec and a diff, and nothing
else. That asymmetry is the whole design.

## How it works

| Agent | Job | How it runs |
|---|---|---|
| **Claude Code** | all implementation, all file edits, orchestration | interactive, your session |
| **Gemini CLI** | web research, primary reviewer, mechanical build tasks | headless, `--output-format json` |
| **Codex CLI** | tiebreaker only | headless, `exec --sandbox read-only --ephemeral` |

Codex is deliberately barely used. It runs read-only and ephemeral, once for a real
disagreement or once at the end — the tool is aimed at people on free or low tiers, and
it warns you when you have already called it.

```
align  →  research  →  plan  →  build  →  review  →  done
   │                     │                   │
   │                     │                   └─ max two rounds, then a human
   │                     └─ roadmap written to TASKS.json, ordered by value
   └─ human gate: SPEC.md must say STATUS: APPROVED
```

Six rules hold it together:

| | |
|---|---|
| **One driver, two consultants** | Only Claude has memory between steps. |
| **Alignment before work** | Nothing past `align` runs until a human writes `STATUS: APPROVED` in `SPEC.md`. Enforced in code — `gate` exits non-zero. |
| **Reviewers never see the repository** | They get the spec and the change. That is what makes reviewing affordable. |
| **Findings need coordinates** | A finding without a file and line is discarded unread, because reviewers otherwise produce plausible-sounding nothing. |
| **Two rounds, then a human** | The loop cannot run forever by construction. |
| **Markdown is the protocol** | No database, no message bus, no daemon. Every piece of state is a file you can open in a text editor mid-run and edit. |

It is a coordination harness, not a framework and not an agent runtime. It does not make
the models better. It stops them duplicating each other's context and gives you one place
to look.

## Requirements

- **Python 3.8+**, standard library only. Nothing to install, no dependencies.
- **Your own accounts.** SyncAgent bundles no models and no API keys. You need working
  Anthropic, Google, and OpenAI access, and you install the three CLIs yourself:

| CLI | Install docs |
|---|---|
| Claude Code | https://docs.claude.com/en/docs/claude-code/setup |
| Gemini CLI | https://github.com/google-gemini/gemini-cli |
| Codex CLI | https://github.com/openai/codex |

You can run it with only Claude and Gemini installed; you lose the tiebreaker and nothing
else.

## Install

```bash
git clone https://github.com/AriyanAzami/SyncAgent.git ~/tools/SyncAgent
```

Then add an alias so you can call it from anywhere.

<details open>
<summary><b>macOS</b> — zsh is the default shell, so use <code>~/.zshrc</code></summary>

```bash
echo "alias sync='python3 ~/tools/SyncAgent/syncagent.py'" >> ~/.zshrc
source ~/.zshrc
```

macOS ships no `python` command — only `python3`, from Homebrew, python.org, or the
Command Line Tools. The alias above uses `python3` for that reason. Check yours with
`python3 --version`; if it is missing, `brew install python`.

</details>

<details>
<summary><b>Linux</b> — bash or zsh</summary>

```bash
echo "alias sync='python3 ~/tools/SyncAgent/syncagent.py'" >> ~/.bashrc
source ~/.bashrc
```

</details>

<details>
<summary><b>Windows</b> — PowerShell profile</summary>

```powershell
New-Item -ItemType Directory -Force (Split-Path $PROFILE -Parent) | Out-Null
Add-Content $PROFILE 'function sync { python "$HOME\tools\SyncAgent\syncagent.py" @args }'
. $PROFILE
```

The first line is not optional. If you have never customised PowerShell, the folder
holding your profile does not exist yet, and `Add-Content` creates files but not the
directories above them — so on a clean machine the second line fails on its own with
`Could not find a part of the path`. This is more likely than it sounds when Documents is
redirected to OneDrive, which puts the profile somewhere you have certainly never
created by hand.

Windows PowerShell 5.1 (`powershell.exe`) and PowerShell 7 (`pwsh`) read *different*
profile files. Run the block in whichever one you use — or in both.

If `. $PROFILE` reports that running scripts is disabled, that is the execution policy:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

</details>

Everything below uses `sync`. The alias is for your convenience only — the generated
workspace records the exact interpreter and script path it was created with, so the
agents never depend on your shell configuration.

## Quick start

```bash
sync init ~/work/scheduler-api --track code
cd ~/work/scheduler-api
sync start          # prints the three launch commands
sync dash           # dashboard at http://127.0.0.1:7777
sync usage          # what the session has spent, and how much headroom is left
```

Open two terminals — Claude in one, the dashboard in the other. Then, inside Claude:

```
/align build a REST API for the scheduling service
```

`init` writes the whole scaffold and runs `git init`:

```
scheduler-api/
├── CLAUDE.md                  the loop rules Claude follows
├── GEMINI.md                  consultant instructions for Gemini
├── AGENTS.md                  tiebreaker instructions for Codex
├── .gitignore
├── .claude/
│   ├── settings.json          deny rules that survive skip-permissions
│   └── commands/              /align /research /plan /build /review /wrap /resume
└── .syncagent/
    ├── SPEC.md                the approval gate
    ├── TASKS.json             the roadmap, ordered by value
    ├── QUESTIONS.md           agents ask, you answer
    ├── STATUS.md              live progress, Claude keeps it current
    ├── RESEARCH.md            Gemini's findings, URLs required
    ├── DECISIONS.md           append-only record of settled arguments
    ├── config.json            models, effort, token budgets
    ├── state.json             current phase and review round
    ├── reviews/               one file per review round
    ├── research/              one file per non-review consult
    ├── inputs/                material you drop in yourself
    ├── refs/                  read-only outside material
    └── prompts/               the role prompts — edit these to tune behaviour
```

## Tracks

Same loop, different spec sections and different review criteria.

| `--track` | For | What the reviewer checks |
|---|---|---|
| `code` | software projects | correctness, edge cases, error handling, security, acceptance criteria |
| `assignment` | coursework, essays, reports | rubric coverage, argument structure, citations, repetition |
| `resume` | resume and cover letter tailoring | keyword match against the posting, verifiability, weak verbs, ATS formatting |
| `generic` | everything else | completeness against the criteria, unsupported claims |

`assignment` and `resume` use a `draft` phase where `code` uses `build`.

The `resume` track's spec has a **Truth constraints** section, and its reviewer checks
every bullet against your real base resume. Tailoring should sharpen what is true, not
invent it — inventing experience is the one failure mode that actually costs someone an
interview, so the constraint is written into the prompt rather than left to good manners.

## The loop

```
/align      Claude drafts SPEC.md, sends the raw request (not the repo) to Gemini
            for its blocking questions, merges both sets into QUESTIONS.md, stops.

  ↓  you answer QUESTIONS.md and change SPEC.md to STATUS: APPROVED

/research   only if the spec's Unknowns section is non-empty. Gemini answers with
            URLs attached; claims without one are struck.
/plan       Claude decomposes the spec into TASKS.json and stops for you to read it.
/build      one task per cycle: tasks next → tasks start → implement → tasks done.
/review     Gemini returns JSON findings. BLOCKERs get fixed, MAJORs go to you,
            NITs are ignored. Two rounds maximum.
/wrap       optional final Codex pass, then close out.

/resume     any time a session dies. Prints where you were and what is next.
```

The gate is real. `sync gate build` exits with an error while `SPEC.md` still says
`DRAFT`, so the phase cannot advance from a prompt alone. Alignment is the only point
where correction is cheap; after it, you are paying three models to build the wrong
thing.

## The roadmap

`/plan` writes `.syncagent/TASKS.json` — the reason a session that dies at 70% costs one
task instead of the project.

```json
{
  "id": "T3",
  "title": "JWT middleware",
  "files": ["src/auth/jwt.py", "tests/test_jwt.py"],
  "depends_on": ["T1"],
  "acceptance": "AC-4: expired tokens return 401",
  "value": "high", "size": "M", "assignee": "claude",
  "status": "todo", "commit": null
}
```

**Order is value-first, not dependency-first.** A topological sort gives a *valid* order;
many valid orders exist. Among tasks whose dependencies are met, SyncAgent picks highest
`value`, then smallest `size`, then lowest id. Dependency order alone can leave you at
60% completion with 60% of a scaffold and nothing that runs. This ordering leaves you
with something usable — which matters most exactly when you hit a usage limit partway
through.

`value` is judged by how useful the project would be *if it stopped right after this
task*, not by technical importance. That distinction is the whole feature.

**Routing follows scarcity.** Claude quota is the scarce resource, so `assignee` is
`claude` for anything where judgment changes the outcome — architecture, data models,
concurrency, security paths, the first instance of any pattern — and `gemini` only for
mechanical work against a pattern that already exists, with the exemplar named in the
task's `notes`. Codex stays the tiebreaker and is assigned nothing.

**Parallelism is narrow and off by default.** `sync tasks parallel` returns a batch only
when the tasks' `files` sets are provably disjoint; a task with an empty `files` list has
an unknown footprint, so it conflicts with everything and comes back alone. Fan out for
*investigation* — "read these four modules and report how auth flows" — and stay serial
for *implementation*.

Every `tasks done` commits as `T3: JWT middleware`, one task per commit, so the ids stay
resolvable in the history. `sync resume` then costs a fixed, tiny payload: phase, counts,
any task left mid-flight (reset to `todo`, with a warning to check `git status`), the
next task, and anything blocked. Nothing else — no repository read, no spec restatement.
Rediscovery is the most expensive thing a resumed session can do.

## What the reviewer receives

Assembled by `collect_change()`, which handles the four cases that quietly break naive
diff collection:

- **No commits yet.** A fresh `git init` has no `HEAD`, so `git diff HEAD` fails. It
  checks with `rev-parse` first and falls back to staged plus unstaged.
- **Brand-new files.** `git diff` never shows untracked files, which is most of what an
  agent produces. Untracked files are inlined in full.
- **Scaffold noise.** `.syncagent/`, `.claude/`, and the three instruction files are
  excluded, so the reviewer reviews your work rather than the harness.
- **Runaway payloads.** Files over 120 KB are named but not inlined, and the whole
  payload is capped at 180 KB with a truncation marker.

Prompts reach both CLIs over **stdin**, never as a command-line argument. A spec plus a
diff will exceed `ARG_MAX` eventually, and that failure looks like an unrelated crash
rather than a size problem.

## Security

Read this part before you run it on anything you care about.

### It launches Claude with permission prompts disabled

`sync start` prints, and `sync start claude` runs:

```bash
claude --dangerously-skip-permissions --model opus
```

The trade, accurately:

- **Deny rules still hold.** Deny rules in `.claude/settings.json` are evaluated before
  the permission mode and cannot be overridden by it. Writes to `.syncagent/refs/`,
  reads of `.env`, `sudo`, and force-push stay blocked with the flag on.
- **`ask` rules still stop.** `git push`, `npm publish`, and `gh release` prompt as
  normal.
- **But a destructive command inside the project folder now runs without asking.** A
  wrong `rm` happens silently. `init` runs `git init` for exactly this reason, and the
  one-task-one-commit rule means you are rarely more than one task from a checkpoint.
- **The flag is only as safe as your inputs.** When an agent reads a web page, a PDF, or
  a linked reference, that content can contain instructions aimed at the agent. This is a
  known failure mode of this setup, not a hypothetical. Treat anything in `refs/` that
  you did not write as untrusted.

If that trade does not suit you, swap the flag for `--permission-mode acceptEdits` and
launch Claude yourself. The tool works the same either way — the flag removes typing, not
a safety mechanism you cannot live without.

`sync ref <path>` symlinks (or `--copy`s) outside material into `.syncagent/refs/`, which
the deny list makes read-only. The flag removes the prompts; the deny list keeps the
blast radius inside the folder.

The dashboard binds to `127.0.0.1` only. It is not reachable from your network.

## Costs and token discipline

The design is mostly about not paying twice for the same context:

- Reviewers get the spec and the change, never the repository.
- Codex is a tiebreaker. It runs `--sandbox read-only --ephemeral` and leaves nothing on
  disk. Call it more than a couple of times and it tells you what you have already spent.
- Mechanical tasks route to Gemini, whose limits are more generous than Claude's.
- Long agent output goes to files under `.syncagent/`, not into Claude's conversation.
- `resume` replaces rediscovery with a fixed small payload.

Budgets drive the dashboard gauges. They live in `.syncagent/config.json` and are yours
to match to your actual plan:

```json
"codex": { "model": "gpt-5-codex", "effort": "medium",
           "budget_tokens_per_day": 120000 }
```

**Claude's meter is measured, not self-reported.** Claude Code appends every assistant
turn, with the exact usage block the API returned, to
`~/.claude/projects/<slugged-cwd>/<session-id>.jsonl`. SyncAgent reads that file, so the
dashboard tracks the live session within seconds and needs nothing from Claude itself:

```bash
sync usage
```

```
plan max-5x  -  weighted tokens (output x5, cache read x0.1)

this session     30 calls     2,341,498 raw       432,925 weighted
  in 1,911 / out 24,609 / cache write 66,498 / cache read 2,248,480

5h window      [######......................]  23.2%   2,317,591 / 10,000,000
               resets in 3h 51m
7d window      [#...........................]   1.9%   2,317,591 / 125,000,000

burn rate      1,840,931 weighted tok/hour
headroom       4h 10m of work left (binding limit: window)
```

`sync log` still exists for older workspaces, and the panel falls back to it when no
transcripts are found. Gemini's and Codex's numbers come from their JSON output and are
exact.

**Weighted tokens.** A cached read costs a tenth of a fresh input token and an output
token costs five times one, so a raw total is a poor proxy for what a subscription is
being charged. Every count is weighted by its class before it hits a gauge:

```json
"limits": {
  "plan": "max-5x",
  "window_hours": 5,
  "window_tokens": 10000000,
  "weekly_tokens": 125000000,
  "weights": { "input": 1.0, "output": 5.0, "cache_write": 1.25, "cache_read": 0.1 }
}
```

**The ceilings are estimates.** Anthropic does not publish subscription limits in tokens.
The presets (`pro`, `max-5x`, `max-20x`) are calibrated guesses, and the whole point of
putting them in `config.json` is that you correct them the first time you hit a wall:

```bash
sync usage --plan max-20x
sync usage --window-tokens 30000000 --weekly-tokens 400000000
```

The percentages are only as good as those two numbers. The burn rate, the raw counts and
the reset clock are measured and exact.

## Configuration

`.syncagent/config.json` holds models, reasoning effort, and daily token budgets:

```json
{
  "version": "1.0",
  "name": "scheduler-api",
  "track": "code",
  "agents": {
    "claude": { "model": "opus",           "effort": "high",    "budget_tokens_per_day": 2000000 },
    "gemini": { "model": "gemini-2.5-pro", "effort": "default", "budget_tokens_per_day": 1000000 },
    "codex":  { "model": "gpt-5-codex",    "effort": "medium",  "budget_tokens_per_day": 120000 }
  },
  "limits": {
    "plan": "max-5x", "window_hours": 5,
    "window_tokens": 10000000, "weekly_tokens": 125000000
  }
}
```

`limits` is what the subscription gauges read; see
[Costs and token discipline](#costs-and-token-discipline).

The real tuning surface is `.syncagent/prompts/` — `align.md`, `research.md`,
`review.md`, `tiebreak.md`. They are plain markdown with `{SPEC}` and `{INPUT}`
placeholders, and they are what the consultants actually do. Edit them freely. Four rules
in there earn their keep:

- **No file:line, no finding.** Discarding uncited findings is what stops review theatre.
- **Empty findings is a valid answer.** Without saying so, reviewers manufacture problems.
- **Two rounds, then a human.** Round three has not been worth it yet.
- **No URL, no claim.** Applied to research, this is most of the hallucination defence.

`.claude/commands/` holds the slash commands. `CLAUDE.md` holds the loop rules Claude
reads at the start of every session, including the exact CLI invocation for this machine.

## Command reference

| Command | Does |
|---|---|
| `sync init <path> --track <t> [--name N] [--force]` | build the workspace, run `git init` |
| `sync start [all\|claude\|gemini\|codex]` | launch one CLI, or list all three with flags |
| `sync ask gemini --role research\|review --text "..."` | headless consult; `review` captures the diff itself |
| `sync ask codex --role tiebreak --text "..."` | settle a disagreement |
| `sync ref <path> [--copy] [--rename N]` | link outside material in read-only |
| `sync gate <phase>` | advance the phase; enforces the spec gate and roadmap validity |
| `sync log --role build --tokens N [--note "..."]` | Claude self-reports its usage (fallback only) |
| `sync status` | one-screen text summary |
| `sync usage [--json] [--plan P] [--window-tokens N] [--weekly-tokens N]` | measured spend, window and weekly headroom, burn rate |
| `sync dash [--port N]` | dashboard on `127.0.0.1`, polls every 2 seconds |

**Roadmap:**

| Command | Does |
|---|---|
| `sync tasks validate` | schema, duplicate ids, unknown dependencies, cycles |
| `sync tasks list` | the roadmap as a table, with the next task marked |
| `sync tasks next` | the single next task as JSON; exit 1 if none ready |
| `sync tasks parallel [--max N]` | a batch whose `files` sets are provably disjoint |
| `sync tasks start <id> [--force]` | mark in progress; refuses on unmet dependencies |
| `sync tasks done <id> [--no-commit]` | mark done, commit as `<id>: <title>`, record the sha |
| `sync tasks block <id> --reason "..."` | mark blocked, record why |
| `sync resume` | where you were, what is next, what is blocked |

`ask` also takes `--show` to print the answer, and `--force` to silence the Codex
overuse warning.

## Troubleshooting

**`'gemini' is not on your PATH`** — check with `which claude gemini codex` (PowerShell:
`Get-Command claude, gemini, codex`). The alias runs Python, not the CLIs; they have to
be installed separately.

**macOS: `command not found: python`** — macOS has no `python`, only `python3`. Use
`python3` in your alias. The generated workspace bakes in the full interpreter path at
`init` time, so the agents are unaffected either way.

**Windows: `Add-Content $PROFILE` fails with `Could not find a part of the path`** — the
directory holding your PowerShell profile has never been created. Run
`New-Item -ItemType Directory -Force (Split-Path $PROFILE -Parent)` first, then append.

**Gemini returns nothing, or the output file contains your own prompt back** — that is
almost always authentication. Run `gemini -p "hi" --output-format json` directly and
complete the login it asks for.

**Codex fails immediately** — it wants a git repository. `sync init` runs `git init` for
you, but if you moved or copied the folder without `.git`, re-run it.
`--skip-git-repo-check` is already passed.

**Dashboard shows stale or missing numbers** — it polls `.syncagent/telemetry.jsonl`
every 3 seconds. If a consult is missing entirely, an agent was called directly instead
of through `sync ask`, and the telemetry was never written.

**`No TASKS.json yet`** — the roadmap has not been written. Run `/plan` in Claude.
Workspaces created before the roadmap existed keep working without one; `gate` warns
rather than refusing.

**`gate build` refuses with a validation error** — the roadmap is malformed and an agent
would follow it anyway. Fix what `sync tasks validate` names.

**`Not inside a SyncAgent workspace`** — every command except `init` walks upward looking
for a `.syncagent/` directory. You are outside one.

## Contributing

Issues and pull requests welcome. One rule: standard library only — see
[CONTRIBUTING.md](CONTRIBUTING.md). Tests are `unittest`, run with:

```bash
python -m unittest discover -s tests
```

## License

MIT © [Ariyan Azami](https://github.com/AriyanAzami). See [LICENSE](LICENSE).
