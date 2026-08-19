---
name: resume
description: What a good resume, CV or cover letter looks like, and the bar to hold one to. Use when the user wants a resume or CV reviewed, rewritten, tailored to a job posting, or checked before applying.
---

# Resume work

This sets the bar. The `table` skill runs the loop; this is what you copy into
`GOAL.md` under **What "good" means** so the advisors and quality control are
judging the same thing.

## What you need before starting

The resume, and the posting it is aimed at. A resume with no target is a resume
you cannot judge — "good in general" is not a bar. If the user has not given you
a posting, ask for one, or ask for the role and level and write the target down
in `GOAL.md` yourself.

Both belong in `input/`. Do not edit anything in there; the rewrite goes to
`output/`.

## The bar

Adapt the specifics, keep the shape:

- **Fits one page** (two if the user has more than about ten years, or it is an
  academic CV).
- **Every bullet leads with an outcome, not a duty.** "Cut deploy time from 40
  to 6 minutes by…" not "Responsible for the deployment pipeline". If nothing
  came of the work, the bullet is filler and should go.
- **Numbers where numbers exist**, and no invented ones. If the user does not
  know the figure, ask — do not estimate on their behalf.
- **The match is visible in ten seconds.** The strongest evidence for *this*
  posting is in the top third of page one. This is the single most common
  failure and the hardest one to see from the inside.
- **The posting's own words appear where they are true.** Screening is keyword
  matching before it is human. Mirroring real vocabulary is honest; claiming a
  skill because the posting listed it is not.
- **No filler.** "Detail-oriented team player with a passion for" is a line that
  costs space and says nothing. Cut it and give the space to evidence.
- **Consistent shape** — one date format, one tense rule (present for the
  current role, past for everything else), one bullet style.

## What to send an advisor

The single most useful question, because it is the one thing you cannot check
from inside the draft:

```bash
python ask.py codex <job> -m "You are screening for the posting in input/. You have ten seconds on this resume. What do you conclude, and what did you miss because of where it sits on the page?"
```

Good follow-ups, one per round:

- "Which bullets describe duties rather than results? Quote each one."
- "What does the posting ask for that this resume never answers?"
- "Where does this overclaim relative to the evidence behind it?"

## Lines you do not cross

- **Never invent experience, dates, titles, or numbers.** Not to fill a gap, not
  to match a posting, not because it is probably about right. If the resume is
  thin, say so — that is a real finding and the user can act on it.
- **Do not smooth over a gap** the user has not asked you to address.
- **Keep their voice.** A resume that reads like a template is worse than one
  that reads like a person, even a slightly awkward person.

## Cover letters

Same loop, different bar: three short paragraphs, a specific reason for *this*
employer that could not be pasted into another application, and no sentence that
merely restates a resume bullet. If a paragraph would survive a find-and-replace
of the company name, it is not doing any work.
