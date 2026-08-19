# table/

Where the agents talk. One folder per job:

```
table/resume-2027/
  GOAL.md     what we are making, and what "good" means
  STATUS.md   the running log — round number, state, what happened
  notes/      one file per advisor call
```

`GOAL.md` and `STATUS.md` are the shared ground: Claude Code writes them, every
advisor reads them, and quality control judges against `GOAL.md` rather than
against anyone's opinion.

Make one with `python ask.py new <name>`.

The job folders are gitignored — they are your working state, not source.
