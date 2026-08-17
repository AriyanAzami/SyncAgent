<div align="center">

# SyncAgent

**A table your AI agents sit around.**

Put a need on the table. One agent picks it up, leaves a markdown file, and says who
should take it next. You watch the whole thing on a local dashboard and can retarget any
step. One agent runs at a time — never two.

Made by **[Ariyan Azami](https://github.com/AriyanAzami)**

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-1B211E?style=flat-square)](https://www.python.org/downloads/)
[![Dependencies: none](https://img.shields.io/badge/dependencies-none-3B5E4A?style=flat-square)](#requirements)
[![Platforms](https://img.shields.io/badge/macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-supported-2E5C8A?style=flat-square)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-7A6A2F?style=flat-square)](LICENSE)

</div>

---

## Start here

```bash
git clone https://github.com/AriyanAzami/SyncAgent.git
cd SyncAgent
python sync.py
```

That is the whole setup. It finds which AI CLIs you have, makes a `table/` folder, and
opens a dashboard. There is no install, no alias, no config file to write, and nothing to
learn before you see it work.

Type what you need into the box. That's it.

## Your first five minutes

**1. Check your seats work.** Being installed is not the same as being able to answer:

```bash
python sync.py doctor
```

```
  antigravity  ready   gemini-3.1-pro-high
  gemini       disabled in config.json
  claude       ready   claude-opus-5
  codex        ready   codex
```

**2. Put your material on the table.** Anything the agents should read goes in
`table/inputs/` — a resume, a job posting, a draft, a spec. You never paste it into a
chat, and you never paste it twice:

```bash
cp ~/Documents/resume.pdf table/inputs/
cp ~/Downloads/job-posting.md table/inputs/
```

**3. Ask.** In the dashboard box, or from the terminal:

```bash
python sync.py ask "How is my resume for this posting? Both are in table/inputs/" --lens resume
```

**4. Read what came back.** Every turn is a file:

```
table/001-how-is-my-resume/
  01-antigravity-research.md what the posting really asks for
  02-claude-critique.md      the judgment, and where the resume falls short
  ANSWER.md                  the synthesis — read this one
table/out/
  resume-review.md           the actual rewrite, from the scribe
```

That's the loop. Everything below is detail you only need when you want to change
something.

### A real example of what you get

Asked whether to move sessions from Postgres to Redis, with a four-line note in
`table/inputs/`, the `decision` lens produced this — abbreviated:

> **Recommendation: no, don't move sessions to Redis.**
>
> 40 req/s is not load. 2.1M rows is the real signal, and it points somewhere other than
> Redis — for that many *live* sessions to accumulate, expired rows are almost certainly
> never deleted. That's a garbage-collection bug. Redis would paper over it, which is the
> failure mode worth naming: the symptom vanishes, the bug stays.
>
> **What would have to be true for Redis to be right:** session reads are a measured share
> of p99; per-request writes are hurting unrelated queries; 10x growth on a known
> timeline; or Redis is already in production.

Then it stopped and handed the topic back to *me*, because the remaining question —
what the person who suggested Redis had actually observed — was not in the folder and
could not be guessed.

**That handoff is the feature.** An agent that stops and says "this needs a fact I don't
have" is worth more than one that fills the gap confidently.

## What problem this solves

If you pay for more than one AI subscription, you end up pasting the same thing into
three terminals — the resume into one, the job posting into another, then the first
one's answer into the third to check it. Every paste costs tokens for context those
models already had somewhere else, and you are the one holding the thread together.

The obvious fix is to let the agents talk to each other, and that reliably makes it
worse. Point three models at one question and they spend most of their tokens
re-establishing context and agreeing with each other. You get a transcript instead of an
answer, at triple the price.

SyncAgent does something narrower. **One agent works at a time, on a shared folder.** Each
one reads a small brief plus what the previous agents concluded — never your repository,
never the whole conversation — writes its answer to a markdown file, and names who should
take it next.

## How it actually works

Say you drop this on the table:

> How is my resume for the Northwind posting? Both files are in `table/inputs/`.

```
you ──▶ antigravity       reads both files, researches deep
          │               writes 01-antigravity-research.md
          ▼
        claude            reads only Antigravity's findings — not its whole turn.
          │               Adds judgment, rewrites the resume into table/out/
          │               writes 02-claude-critique.md
          ▼
        "to: user"        stops, because the remaining gaps are facts only you have
```

Nobody re-reads the posting. Nobody pastes anything. Claude never sees the research
Antigravity did to reach its conclusions — only the conclusions, because that is all it
needs to disagree with them.

Every step leaves a file you can open. Nothing is hidden in a chat history.

## The table is a folder

That is the entire mental model:

```
table/
  config.json                who sits where, and how deep each one goes
  inputs/                    your material. Every seat reads it, none may write to it
  out/                       real deliverables. Only the scribe writes here
  001-how-is-my-resume/
    NEED.md                  what you asked, verbatim
    BRIEF.md                 the shared context every seat reads. Capped
    01-antigravity-…-.md     one file per turn
    02-claude-critique.md
    ANSWER.md                the synthesis you actually read
    topic.json               who did what, what it cost, who they handed to
```

No database, no message bus, no daemon. You can open any of it in a text editor
mid-run, edit it, and the next agent will read what you wrote.

## Seats

| Seat | CLI | Default job | Depth | Writes files? |
|---|---|---|---|---|
| **Antigravity** | `agy` | research and evidence | `deep` | no |
| **Claude** | `claude` | judgment and critique | `light` | **yes — the scribe** |
| **Codex** | `codex` | tiebreak, on request | `glance` | no |
| **Gemini** | `gemini` | research and evidence | `deep` | no — *ships disabled* |

Antigravity holds the research chair because Google withdrew the Gemini CLI's free tier
for individual accounts. It runs a Gemini model (`gemini-3.1-pro-high` by default), so the
deep-research seat is still a Gemini — just reached through `agy`. The plain `gemini` seat
is still there and still works if you have an API key or a paid Code Assist plan; enable
it in `table/config.json`.

You can reorder them, change any depth, or hand a job to one seat directly.

**Advisory seats genuinely cannot write.** They are launched sandboxed — Antigravity with
`--sandbox`, Codex with `--sandbox read-only`, Claude with `--permission-mode dontAsk` —
so it is enforced, not requested. Verified on a real run: a sandboxed seat reads
`table/inputs/` happily, and a write silently produces no file. Exactly one seat is the **scribe** and is the only one that can produce a real
deliverable in `table/out/`. Without a scribe, nobody is doing the work; with three,
they overwrite each other.

### Depth is bytes, not adjectives

This is the part that keeps the bill down. Depth controls *what a seat is physically
sent*, not just how its prompt is worded:

| Depth | Receives | Asked for |
|---|---|---|
| `deep` | the brief + every earlier turn in full | a full document, sources required |
| `light` | the brief + only the **Findings** of earlier turns | under 400 words |
| `glance` | the brief + only the **previous** turn's findings | under 150 words, a verdict |

A `light` seat cannot re-litigate reasoning it was never shown. In a real run, the `light`
seat wrote six paragraphs and the `glance` seat wrote four lines that added a verdict
without redoing any of the analysis.

And when a seat takes a **second** turn on the same topic, it resumes its own session
(`claude --resume`, `codex exec resume`) and is sent **nothing** it already has — not even
the brief.

## Handoffs

Every turn ends with a block the runner parses:

```
## Handoff
to: claude
job: check whether the container migration was actually Kubernetes
why: you have the base resume and I only have the summary
```

- `to: <seat>` — that seat goes next. If it isn't the one already planned, it's inserted
  as a detour and the plan resumes afterwards.
- `to: user` — stops and waits for you. Used when the gap is a fact only you have.
- `to: none` — the need is met. The rest of the plan is skipped.

Detours are capped (`max_hops`, default 3) so two agents cannot volley forever.

## The dashboard

`python sync.py` opens `http://127.0.0.1:7777` (localhost only, never your network).

- **Put a need on the table** — type it, pick a lens, send.
- **Divide it up** — build the plan yourself: which seat, what depth, what job, in what
  order. Or leave it and the default relay runs.
- **Seats** — who is live, how many turns each has taken, and *why a seat can't run* if
  it can't.
- **The chain** — every turn as a card you can expand and read, with handoff arrows
  between them.
- **Claude limits** — the five-hour window, asked of Claude every minute. The weekly
  limit is one click away. See below.
- **The queue** — "gemini is working, 1 waiting". One seat at a time, visibly.

## Lenses

A lens swaps one paragraph of focus into the prompt. Pick it per topic, not per install.

| Lens | Focuses on |
|---|---|
| `general` | completeness, unsupported claims |
| `resume` | keyword match, verifiability, weak verbs, ATS formatting |
| `code` | correctness, edge cases, security — every finding needs a file and line |
| `writing` | argument structure, repetition, citations |
| `decision` | the real options, what each costs, a named recommendation |

The `resume` lens carries a **truth constraint**: tailoring sharpens what is true, it does
not invent. If a bullet can't be traced to your real resume, the agent must say so rather
than write it. Inventing experience is the one failure here that actually costs someone
an interview, so it's written into the prompt rather than left to good manners.

## Claude's limits come from Claude

`/usage` is a local slash command, so `claude -p /usage` answers off the same meter the
app itself draws: no API call, no tokens, about a quarter of a second. The dashboard asks
once a minute and shows what comes back.

```bash
python sync.py usage
```

```
5h window          [####........................]  13.0%
                   resets Aug 16, 10:29pm (America/Toronto)
week (all models)  [#####.......................]  17.0%
                   resets Aug 22, 6:59am (America/Toronto)
```

On the dashboard the five-hour window is the panel — one percentage, one bar, one reset
time. The weekly limit sits behind a dropdown, because it is the number you check
occasionally rather than the one you watch while you work.

**Why not count the tokens.** Earlier versions read every assistant turn out of
`~/.claude/projects/<slug>/<session>.jsonl`, weighted the four token classes by price and
measured the total against a ceiling. Anthropic does not publish those ceilings, so the
ceiling was a guess, and a gauge reading 23% when you are really at 60% is worse than no
gauge. Asking beats estimating.

## Requirements

**Python 3.8+**, standard library only. Nothing to install.

**Your own accounts.** SyncAgent bundles no models and no API keys. You install the CLIs
yourself and it uses whatever you're already paying for:

| CLI | Install |
|---|---|
| Antigravity (`agy`) | https://antigravity.google |
| Claude Code | https://docs.claude.com/en/docs/claude-code/setup |
| Codex CLI | https://github.com/openai/codex |
| Gemini CLI *(optional)* | https://github.com/google-gemini/gemini-cli |

`agy` does not always put itself on your PATH — it ships an `agy install` subcommand for
that. SyncAgent looks in its install directory anyway, so it works either way.

**One is enough to start.** With two you get the cross-check that is the point of the
tool. Missing seats are simply disabled.

Check what actually works — this costs a few tokens and is worth it:

```bash
python sync.py doctor
```

```
  gemini   BLOCKED    Gemini's free CLI tier has been withdrawn for individual
                      accounts. Set GEMINI_API_KEY (from aistudio.google.com/apikey)
                      or GOOGLE_CLOUD_PROJECT, then retry.
  claude   ready      claude-opus-5
  codex    ready      codex
```

A seat can be installed, logged in, and still unable to answer. `doctor` makes one real
call per seat, because that is the only thing that tells the difference.

## Commands

Everything is optional — the dashboard does all of it.

| Command | Does |
|---|---|
| `python sync.py` | set up if needed, then open the table |
| `python sync.py ask "..."` | put a need on the table from the terminal |
| `python sync.py ask "..." --lens resume --seat gemini --seat claude` | pick the lens and the running order |
| `python sync.py doctor` | check every seat with one tiny real call |
| `python sync.py usage` | what Claude says is left of your limits |
| `python sync.py list` | topics on the table |
| `python sync.py setup --path DIR` | make a table somewhere without opening the dashboard |

`python -m syncagent` works identically if you prefer it.

## Security

**The scribe writes files.** It runs with edits auto-accepted so it can produce
deliverables without prompting you mid-run. Deny rules in `.claude/settings.json` are
evaluated *before* the permission mode and still hold: `table/inputs/` is read-only,
`.env` is unreadable, `sudo` and piped-curl-to-shell are blocked.

**Advisory seats are sandboxed** at the CLI level, not merely instructed.

**Treat `table/inputs/` as untrusted.** When an agent reads a PDF, a web page, or a
document you didn't write, that content can contain instructions aimed at the agent. This
is a real failure mode of this kind of tool, not a hypothetical.

**The dashboard binds to `127.0.0.1` only** and is not reachable from your network. It
reads files only from inside a topic folder, and the filename is pattern-checked.

## Troubleshooting

**Gemini fails with `IneligibleTierError`** — Google withdrew the free Gemini CLI tier for
individual accounts, which is why the `gemini` seat ships disabled and Antigravity holds
the research chair instead. If you want the `gemini` seat back, set `GEMINI_API_KEY` from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey) or `GOOGLE_CLOUD_PROJECT`
for a paid Code Assist plan, then enable it in `table/config.json`.

**An Antigravity turn returns nothing** — it reports `SUCCESS` with an empty response when
a tool it reached for was denied. Give that seat reasoning work, or make it the scribe if
it genuinely needs to write.

**A very long Antigravity prompt gets truncated** — `agy -p` takes the prompt as a
command-line argument rather than on stdin, and Windows caps a command line at 32,767
characters, so prompts are capped at 28,000 with a visible marker. Only a `deep` seat
carrying several earlier turns gets near it.

**A seat is "not on your PATH"** — check with `which claude gemini codex` (PowerShell:
`Get-Command claude, gemini, codex`). SyncAgent runs Python, not the CLIs; you install
those separately.

**macOS: `command not found: python`** — macOS ships only `python3`. Use
`python3 sync.py`.

**A turn used far more tokens than expected** — `claude -p` loads your project's
`CLAUDE.md`, hooks and MCP servers the same way an interactive session does. A large
project context makes every turn expensive. Run the table from a folder that isn't a huge
repo.

**Nothing runs after I send** — check the Seats panel. A blocked seat shows the reason,
and the relay stops rather than skipping to a seat you didn't choose.

**`No table/ folder here or above`** — every command except the bare `python sync.py`
expects to be inside a table. Run it with no arguments to create one.

## Contributing

Issues and pull requests welcome. One rule: **standard library only** — see
[CONTRIBUTING.md](CONTRIBUTING.md).

```bash
python -m unittest discover -s tests
```

## License

MIT © [Ariyan Azami](https://github.com/AriyanAzami). See [LICENSE](LICENSE).
