# Smoke-testing the skill

This repo deliberately ships **no sample bibliography of invented citations**. A file of
realistic-looking fake references is a liability: it gets copied, quoted out of context,
and eventually cited for real. Build your own test set instead — it takes two minutes and
tests the thing you actually care about, which is your field's literature.

## Build a mixed set

Take **five references you know are genuine** — from your own published work, or a paper
open in front of you, copied exactly as printed. Then add **three synthetic ones**, made
the way a language model would make them:

1. A real paper with a **wrong DOI** — take a genuine citation and swap its DOI for
   another real paper's. This tests the comparison step, which is the one most tools skip.
2. A **plausible invention** — real, prolific authors from your field, a real journal, a
   title that would perfectly support some claim you have in mind, a well-formed DOI with
   a real registrant prefix and an invented suffix.
3. An **UNVERIFIABLE control** — a genuine book chapter, a government report, or a 1950s
   paper. This one is real, and the skill should say it cannot confirm it rather than
   calling it fake. It is the most important item in the set.

Shuffle them. Do not label them.

## What a passing run looks like

- The five genuine references come back VERIFIED, each with a resolvable DOI or URL.
- The wrong-DOI entry comes back REAL BUT MIS-CITED, naming the DOI mismatch specifically
  and giving the correct DOI.
- The invention comes back LIKELY or CONFIRMED FABRICATED, with the evidence stated: DOI
  unregistered, no title match in the named sources, no matching work by those authors.
- The control comes back UNVERIFIABLE, with a note on why that class of source is poorly
  indexed and what a human should check.
- Every input reference has an output row.

## What a failing run looks like

In rough order of severity:

- **The control is called fabricated.** The worst outcome. This is the failure that gets
  a real researcher accused of making things up. File it as a bug.
- **The invention passes as verified.** Check whether the model looked it up at all, or
  leaned on recognition — a verdict with no named source is the tell.
- **The wrong-DOI entry passes.** The lookup ran but the comparison did not.
- **A verdict arrives without evidence.** Even a correct verdict is not usable if the
  report does not say what was searched and what was found.

## Testing the DOI script alone

```bash
python scripts/check_dois.py --file examples/your-test-set.txt
```

The script accepts prose, so you can point it at a whole reference list. Exit code 1 if
any DOI is unregistered.
