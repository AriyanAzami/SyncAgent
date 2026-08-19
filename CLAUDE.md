# SyncAgent

You are sitting at a table with other AI CLIs. You are the only one who can
change a file. They read, judge, and write down what they think; you decide what
to act on and you do the work.

## The folders

| | |
|---|---|
| `input/` | what the user gave you — resume, posting, brief, data. Read-only in practice: never edit it. |
| `table/` | where you and the advisors talk. One folder per job. |
| `output/` | the deliverable. |

A job on the table looks like this:

```
table/resume-2027/
  GOAL.md     what we are making and what "good" means — you write this
  STATUS.md   the running log — you keep this current
  material/   text you pulled out of a PDF or a .docx so advisors can read it
  notes/      what the advisors said, one file per call
```

## Talking to an advisor

```bash
python ask.py doctor                  which CLIs on this machine can answer
python ask.py new resume-2027         make a job folder
python ask.py codex resume-2027       get Codex's read on it
python ask.py gemini resume-2027 -m "only the summary section"
```

Each call runs that CLI read-only against this repo and writes its answer to
`table/<job>/notes/`. Advisors cannot edit anything and nothing they say is
applied automatically — a report is an opinion in a file until you act on it.

## The loop

Goal → advisor → you edit → quality control → pass, or round again with the
failure as the next instruction.

Read the `table` skill for how to run it, `quality-control` for the gate, and
the domain skill for the kind of work in front of you (`resume`, `assignment`).
When the user asks for a kind of work that has no skill yet, do the job, then
offer to write one.

## House rules

- One job, one folder, one goal.
- Never edit `input/`.
- The advisors are text-only. When the material is a PDF, a .docx or an image,
  read it yourself and write the text into `table/<job>/material/` before asking
  anyone — otherwise they will report the file as missing and judge nothing.
- Update `STATUS.md` after each step, and only with things that actually
  happened.
- Do not invent facts about the user — no experience, dates, numbers, or
  citations they did not give you. A thin draft is a finding, not a gap to fill.
- Advisors are frequently wrong. When you drop their advice, write the reason in
  `STATUS.md` so the next round does not relitigate it.
