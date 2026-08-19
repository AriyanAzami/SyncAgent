---
name: quality-control
description: Judge finished work against the bar written in the job's GOAL.md and return PASS or REVISE with specific reasons. Use at the end of every round on the table, and any time the user asks whether something is good enough, ready to send, or done.
---

# Quality control

A gate, not a review. It answers one question: does this work meet the bar in
`GOAL.md` as it stands right now?

Not "did we improve it". Not "did we address the feedback". Work can absorb
every note an advisor gave and still miss the goal, and that is exactly the
failure this pass exists to catch.

## How to run it

**Read `GOAL.md` first, before the work.** Read it as a checklist. If you read
the draft first you will start judging it on its own terms, which is how a piece
of work that is good but wrong gets through.

**Take each line of "What good means" in turn.** For each one: met, or not met,
and the evidence from the actual file. Quote it. A claim with no quote behind it
is a guess.

**Check the constraints separately.** Length, format, tone, deadline. These are
binary and they are the easiest thing to lose while fixing something else. A
one-page resume that became one and a half pages during a round fails, however
much better the bullets got.

**Then the honest question:** if the user sent this today, would it do the job?
If it would not, find what is stopping it and say that, even if every checklist
line is technically met. The list is a floor, not a ceiling.

## Getting a second opinion

You may have written the thing you are now judging. When the work is going out
into the world — a real application, a graded submission, anything the user
cannot take back — do not be the only judge:

```bash
python ask.py codex <job> -m "Judge this against GOAL.md only. For each line of 'What good means', met or not, quote the evidence. End with PASS or REVISE."
```

Then reconcile: where the advisor is right and you missed it, that is a `REVISE`.
Where it is holding the work to a goal the user does not have, say so in your
verdict and move on.

## The verdict

Write it to `table/<job>/notes/NN-qc.md`. Structure:

```markdown
# Quality control — round 2

**Verdict:** REVISE

## Against the bar
- ✅ One page — 47 lines, fits.
- ✅ Every bullet leads with a result — checked all nine.
- ❌ A backend hiring manager sees the match in ten seconds — the top third is
  a summary and an education block. The first backend signal is line 14
  ("Built a Postgres ingestion path…").

## What has to change
1. Cut the summary to one line or drop it, and lift the two strongest backend
   bullets above the fold.
2. "Collaborated with the team on API design" — still a duty, not a result.
   Either what came of it, or cut it.

## Not blocking
- The skills list could be ordered by relevance. Would help slightly. Not why
  this is a REVISE.
```

Rules for the verdict:

- **`PASS` or `REVISE`, nothing in between.** "Mostly there" is a `REVISE`. If
  you cannot decide, it is a `REVISE` and the reason is that the bar is vague —
  say that, and fix `GOAL.md`.
- **Every `❌` names the fix.** A complaint with no next action is not usable by
  the next round.
- **Separate blocking from nice-to-have.** Everything under "What has to change"
  must be a real reason the work fails the bar. Preferences go under "Not
  blocking" and never trigger another round on their own.
- **`PASS` means send it.** Do not pass work you would want one more look at, and
  do not fail work that meets the bar because you can imagine something better.
  A gate that never passes is the same as no gate — the user just stops running it.

After a `REVISE`, the "What has to change" list is the input for the next round.
After a `PASS`, tell the user plainly: it is done, here is where it is, here is
what changed.
