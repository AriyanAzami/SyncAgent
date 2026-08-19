---
name: table
description: Run a piece of work through the table — write the goal, get outside judgement from Codex, Gemini or Antigravity, apply the changes yourself, then quality-control the result and loop until it passes. Use whenever the user asks to work on a deliverable in this repo (a resume, cover letter, assignment, essay, spec, application) or mentions the table, advisors, rounds, or files sitting in input/.
---

# The table

You are the only agent here who can change a file. The others are advisors: they
read, they judge, they write down what they think, and then they are done. You
decide what is worth acting on.

The whole point is that you are a bad judge of your own output. An advisor that
did not write the draft will see things you cannot. That is the only reason they
are at the table.

## The loop

1. **Set the goal** — one job folder, one goal, written down.
2. **Ask an advisor** — `python ask.py <agent> <job>`, their report lands in `notes/`.
3. **Do the work** — you read the report and edit the real files.
4. **Quality control** — check the result against the bar in `GOAL.md`.
5. **Pass, or go round again** — a fail becomes the instruction for the next round.

Stop when quality control passes, or when the user says stop. Two rounds is
common. Past four you are polishing, not improving — tell the user that instead
of burning another round.

## 1. Set the goal

Ask the user what they want and what "done" looks like, if it is not already
obvious from what they said. One or two questions, not an interview.

```bash
python ask.py new resume-2027
```

That makes `table/resume-2027/` with `GOAL.md`, `STATUS.md`, `material/` and
`notes/`. Fill in `GOAL.md` yourself — the advisors and the quality-control pass
both read it, so it is the one place the standard lives.

The section that matters is **What "good" means**. Write it so that someone who
has never spoken to the user could judge the work against it. "Strong resume" is
useless. "Every bullet leads with a result, fits one page, and a hiring manager
for a backend role can see the match in ten seconds" is a bar.

**Convert anything the advisors cannot read.** They are text-only: a PDF, a
`.docx` or a screenshot comes back to them as a missing file, and they will
happily write you a whole report about material they never saw. You can read
those formats — pull the text out and put it in `table/<job>/material/` as
markdown, keeping the structure. `ask.py` lists that folder for them, and marks
anything still unreadable so they say so instead of guessing.

If there is a domain skill for this kind of work — `resume`, `assignment` — read
it before writing the bar and fold what it says into `GOAL.md`.

## 2. Ask an advisor

```bash
python ask.py codex resume-2027
python ask.py gemini resume-2027 -m "only the summary and the first two bullets"
```

Check what is actually available first with `python ask.py doctor` if you have
not this session. Each call lands one file in `table/<job>/notes/`, numbered in
order. Read it.

Who to ask:

| Advisor | Ask it for |
|---|---|
| `codex` | close reading, structure, anything where being wrong is expensive |
| `gemini` | breadth — what a reader outside the field would notice |
| `antigravity` | research-flavoured questions, "what does this field expect" |
| `claude` | a second Claude with no memory of your draft |

One advisor is usually enough. Ask a second when the first was vague, when the
two would genuinely disagree, or when the user asked for more than one opinion.
Do not ask all four out of thoroughness — you will get four versions of the same
three points and a much slower loop.

The `-m` message is where the round gets its focus. Round one is open: let them
find what they find. Round two should be narrow, and should carry what quality
control just said. An advisor asked "is this good?" for the third time will
invent problems to justify its existence.

## 3. Do the work

Advisors are read-only. Nothing in `notes/` has touched a file — it is an
opinion until you act on it.

Read it critically. Some of what comes back will be wrong, generic, or aimed at
a goal the user does not have. Take what is right. When you drop something an
advisor pushed on, say so in `STATUS.md` in one line, with the reason — that is
the record of a decision, and the next round should not relitigate it.

Deliverables go in `output/`. Source material in `input/` is the user's; do not
edit it.

## 4. Quality control

Read the `quality-control` skill and run its pass. It ends in `PASS` or `REVISE`
plus specific reasons, written to `notes/`.

The rule that makes this worth anything: quality control judges against
`GOAL.md`, not against your effort. "I addressed all the feedback" is not a pass.

## 5. Round again, or stop

On `REVISE`, the reasons become the `-m` for the next advisor call, and the
round number in `STATUS.md` goes up. On `PASS`, tell the user what changed and
where the file is.

## STATUS.md

Update it after each step. Newest at the bottom, one line each, and only for
things that actually happened:

```markdown
**Round:** 2
**State:** revising

## Log
- r1 · goal set, one page, backend roles, results-first bullets
- r1 · codex: summary is generic, 4 of 9 bullets have no outcome → notes/01-codex.md
- r1 · rewrote summary, added outcomes to 4 bullets → output/resume.md
- r1 · QC: REVISE — two bullets still describe duties → notes/02-qc.md
- r2 · dropped codex's "add a skills matrix": the user wants one page
```

That log is what a new session reads to find out where things stand. Keep it
honest — if a round achieved nothing, write that.
