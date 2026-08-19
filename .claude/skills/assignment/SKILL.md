---
name: assignment
description: How to work an academic assignment, essay, report or problem set through the table, and the bar to hold it to. Use when the user is working on coursework, a paper, a lab report, a thesis chapter, or anything marked against a rubric.
---

# Assignment work

The `table` skill runs the loop. This is what goes in `GOAL.md` under **What
"good" means**, and the one thing about coursework that changes how the loop
runs.

## The rubric is the bar

If there is a marking rubric or a grading breakdown, it *is* the bar — copy it
into `GOAL.md` verbatim, criterion by criterion with its weight. Do not
paraphrase it into something more sensible. Quality control checks against the
rubric as written, because that is what the marker will do.

No rubric? Then the assignment brief's own wording is the bar. Pull out every
requirement it states, including the boring ones — word count, citation style,
sections, deadline, file format. Those are where marks quietly disappear.

Everything the user was given goes in `input/`: the brief, the rubric, the
readings, the data, last term's feedback if they have it.

## The bar

- **Answers the question that was asked.** Not the adjacent one that was more
  interesting to write. Check this first and check it against the brief's
  literal wording.
- **Every criterion in the rubric is visibly addressed**, and the ones carrying
  the most marks get the most space. A section worth 40% that gets two
  paragraphs is a predictable loss.
- **Claims are supported.** Evidence, citation, or derivation — whichever the
  field expects.
- **Constraints met exactly**: word count, format, citation style, structure,
  deadline.
- **A marker can find each criterion without hunting.** Signpost with the
  rubric's own language.

## What to send an advisor

```bash
python ask.py codex <job> -m "Mark this against the rubric in input/. For each criterion: the grade band you would put it in, and the sentence that decided it. Be a hard marker."
```

Other rounds worth running:

- "What did the brief ask for that this never answers?"
- "Which claims here are asserted without support? Quote them."
- Technical work: "Check the derivations and the numbers. Where is it wrong?"

Ask a second advisor when the work is heavy on reasoning that can be flatly
right or wrong — proofs, calculations, code, statistics. Two independent passes
catch different errors there. For an essay, one good pass and a hard quality
control is usually more useful than a second opinion.

## The line

This is the user's work with their name on it, submitted under an academic
integrity policy. That policy is between the user and their institution — but
where you can help without touching it, do that instead of the alternative:

- Explain, critique, check reasoning, find gaps, suggest structure, mark against
  the rubric, and point at where an argument breaks.
- Where you would otherwise write the substance for them, say what is missing
  and let them write it. A paragraph you drafted is a paragraph they cannot
  defend in a viva.
- **Never fabricate a citation.** Not a plausible-looking one, not a placeholder
  that reads like a real source. If a claim needs a reference the user does not
  have, flag the claim.

If the user asks for something their policy would not allow, say so once,
plainly, and offer the version you can do. Then get on with it.
