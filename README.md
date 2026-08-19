<div align="center">

# SyncAgent

**Claude Code does the work. The other AIs tell it what's wrong.**

You run Claude Code in this folder and say what you need. It writes down the goal,
hands it to Codex or Gemini for an honest outside read, does the work itself, then
checks the result against the goal — and goes round again if it does not pass.

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
claude
```

Then drop your material in `input/` and say what you want:

> I put my resume in input/ along with the job posting. Get Codex to review it,
> fix what it finds, and don't stop until it's actually good.

That is the whole interface. There is no dashboard, no server, no config file, and
nothing to install — SyncAgent is a folder Claude Code knows how to work in.

## Why

An AI is a poor judge of its own writing. It just produced that draft; asking it
whether the draft is any good gets you a confident yes.

So the judging is done by a different model, from a different vendor, that never saw
the draft being written. Codex reads what Claude wrote and says where it is thin.
Claude fixes it. Then a quality-control pass checks the result against the standard
that was written down *before* anyone started, so "I addressed all the feedback"
cannot be mistaken for "this is good now".

One agent edits. The rest only have opinions.

## The three folders

| | |
|---|---|
| `input/` | what you give them — resume, posting, brief, rubric, data. Never edited. |
| `table/` | where they talk. One folder per job. |
| `output/` | what you get back. |

A job on the table:

```
table/resume-2027/
  GOAL.md     what we are making, and what "good" means
  STATUS.md   the running log — round number, state, what happened
  material/   text pulled out of PDFs so the advisors can read it
  notes/
    01-codex.md    what Codex thought
    02-qc.md       quality control: PASS or REVISE, and why
```

`GOAL.md` is the shared ground. Claude Code writes it, every advisor reads it, and
quality control judges against it rather than against anyone's opinion. Everything
the agents say to each other is a markdown file you can open, and it is all still
there tomorrow.

## The loop

```
     you: "here's my resume, make it good"
        │
        ▼
   ┌─ GOAL.md ─────────── Claude writes down the bar
   │    │
   │    ▼
   │  ask.py codex ────── an outside read, lands in notes/
   │    │
   │    ▼
   │  Claude edits ────── the only agent that touches a file
   │    │
   │    ▼
   │  quality control ─── against GOAL.md, not against effort
   │    │
   │    ├── PASS ───────► output/resume.md, and you're done
   │    │
   └────┴── REVISE ────── the reasons become the next round's question
```

## Asking an advisor

Claude Code runs these for you. You can run them yourself too:

```bash
python ask.py doctor              which CLIs on this machine can actually answer
python ask.py new resume-2027     make a job folder
python ask.py codex resume-2027   get Codex's read on it
python ask.py gemini resume-2027 -m "only the summary section"
```

Each call runs that CLI **read-only** against this folder and writes its answer to
`table/<job>/notes/`. The advisors cannot edit anything, and nothing they say is
applied automatically — a report is an opinion in a file until Claude Code acts on it.

`doctor` makes a real call to each one, because being installed and being able to
answer are different things:

```
  codex        ready      answered in 14.5s
  gemini       blocked    Gemini's free CLI tier is withdrawn for individual
                          accounts. Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT.
  antigravity  ready      answered in 9.8s
  claude       ready      answered in 9.1s
```

Whichever ones you have, work. Nothing here requires all four.

## Skills — teaching it your work

`.claude/skills/` is what makes Claude Code know what to do without being told each
time. Four ship with the repo:

| Skill | What it is |
|---|---|
| `table` | the loop above — goal, advisor, work, quality control, repeat |
| `quality-control` | the gate. `PASS` or `REVISE`, judged against `GOAL.md` |
| `resume` | what a good resume is, and the bar to hold one to |
| `assignment` | coursework: the rubric is the bar, and where the line is |

Add your own. A skill is one markdown file — `.claude/skills/<name>/SKILL.md` — with
a name, a description of when to use it, and your standard written out in plain
English. Copy `resume` and change what "good" means. That is the whole extension
model, and it is the part worth investing in: the loop is generic, your standards
are not.

Or just ask Claude Code to write one after a job goes well. It knows the format.

## What a round actually looks like

> **You:** My resume's in input/ with the posting. Get an outside opinion.
>
> **Claude:** Reading both. The posting is a backend role, three-plus years, heavy on
> data pipelines. I've written the bar into `table/resume-2027/GOAL.md`: one page,
> every bullet leads with an outcome, backend evidence visible in the top third.
> Your resume is a PDF, so I've pulled the text into `material/` for the advisors.
> Asking Codex now.
>
> *(50 seconds)*
>
> **Claude:** Codex screened it in ten seconds like a hiring manager would and never
> reached your pipeline work — it sits at line 14, under an education block. Four of
> your nine bullets describe duties rather than results. It also wants a skills
> matrix; I'm skipping that, it costs a third of the page and you want one page.
>
> Rewriting now.
>
> *(edits)*
>
> **Claude:** Quality control: **REVISE**. The top third is fixed, but two bullets
> still have no outcome and I can't invent the numbers. What came of the migration
> in the second role — how much faster, or how many fewer incidents?

That is the shape of it. Outside judgement, applied by the one agent that can
actually type, checked against a standard written before anyone got attached to
the draft.

## Requirements

- **Python 3.8+**, standard library only. No `pip install`.
- **[Claude Code](https://claude.ai/code)** — the agent that does the work.
- **At least one advisor CLI**, signed in and working:
  [Codex](https://github.com/openai/codex),
  [Gemini CLI](https://github.com/google-gemini/gemini-cli),
  [Antigravity](https://antigravity.google) (`agy`).
  Run `python ask.py doctor` to see where you stand.

macOS, Linux and Windows.

## What this is not

Not an agent framework, not an orchestrator, and not a broadcast that asks four
models the same question and averages them. There is one worker and one standard,
and the only thing the other models contribute is judgement.

Your job folders, your material and your output stay on your machine — `input/`,
`table/` and `output/` are gitignored so a clone of this repo never carries your
resume in it.

## License

MIT — see [LICENSE](LICENSE).
