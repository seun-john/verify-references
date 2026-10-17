---
name: verify-references
description: Check whether citations in a reference list, bibliography, or manuscript are real, and flag ones that are fabricated, hallucinated by an LLM, or garbled. Use when the user asks to verify/check/validate references or citations, asks "are these references real", "did AI make these up", "check my bibliography", or hands over a reference list, .bib file, or manuscript to fact-check. Each entry is looked up in Crossref, OpenAlex, PubMed/Europe PMC and other open indexes, then sorted into verified, real-but-mis-cited, unverifiable, and likely-fabricated.
license: MIT
---

# Verify references

Decide, for each reference, whether the cited work actually exists — and if it does,
whether the citation describes it correctly.

## The one rule that matters

**Never judge a reference from your own memory.** Recognising a title is not evidence.
Model recall is the exact mechanism that produces fabricated citations in the first
place, so it cannot be the thing that audits them. Every verdict must rest on a lookup
performed in this session, and every verdict must name the source that produced it.

The corollary: **"I could not find it" is not "it does not exist."** Open indexes miss
books, chapters, theses, government and NGO reports, standards, most pre-1970 work,
much non-English work, and many conference papers. Conflating absence with fabrication
is the way this skill does real damage — a researcher told their genuine citation is
fake. Use the verdict rubric rather than a gut call.

## Step 1 — Collect the references

Accept whatever form they arrive in: pasted text, a `.docx`/`.pdf` manuscript, a `.bib`
or `.ris` file, or in-text citations. If a `docx` or `pdf` skill is available, use it to
read the manuscript; otherwise ask the user to paste the reference list.

Normalise each entry into these fields, leaving blanks where the citation is silent:

`authors | year | title | container (journal/book/publisher) | volume | issue | pages | DOI | URL | type`

Number them in the order given and keep that numbering to the end. Every input entry
gets an output row — no silent drops, no "and the rest look fine".

Four things reliably go wrong at this stage, all of them observed on real theses:

- **The reference section does not end where the document does.** Appendices,
  questionnaires and consent forms follow it and will be swallowed as references. Stop
  at the first `APPENDIX`, `QUESTIONNAIRE`, `INSTRUCTIONS` or `SECTION A:` heading. One
  36-reference thesis parsed as 185 entries before this cut was applied.
- **Word turns hyphens inside DOIs into en dashes.** `10.1007/978–3-031–34688–0` is what
  gets stored, mixing U+2013 with real hyphens. Naive extraction truncates at the first
  en dash, the stub 404s, and a genuine reference is reported as fabricated. Normalise
  U+2010–U+2015, U+2212 and soft hyphens to `-` before matching anything.
- **Organisational authors are references too.** WHO, UNICEF, UNESCO, the World Bank,
  national ministries and statistics agencies do not match a `Surname, X.` pattern and
  get dropped silently. In public-health and social-policy work they can be a fifth of
  the list.
- **A DOI can be truncated in the source itself.** `https://doi.org/10.1111/csp2.` with
  the suffix missing is an author's copy-paste slip, not an invention. A suffix under
  about five characters means "check the document", not "fabricated".

If the input is a manuscript rather than a bare list, also note **what each reference is
cited for** in the text. A citation that is real but does not support the claim made of
it is its own finding, and is common in AI-drafted writing.

## Step 2 — Look each one up

Work down the cascade until you get a hit. Batch 5–10 references per pass so a long list
stays tractable. Exact calls, and the traps in each source, are in
`references/apis.md` — read it before starting.

1. **DOI, if present.** Resolve it live against doi.org and Crossref. An unregistered
   DOI is the single strongest signal available.
2. **Exact title**, in Crossref and OpenAlex; plus Europe PMC for anything biomedical.
3. **Distinctive phrase from the title**, in case of transcription drift.
4. **Author + year + topic**, to catch a real paper cited under a mangled title.
5. **Grey literature** (CORE) for theses, preprints, institutional reports.
6. **Books and monographs** — `scripts/check_books.py` queries Open Library and
   Crossref's monograph filter, which is where books actually live; Crossref and
   Europe PMC alone will miss even famous ones. Also ClinicalTrials.gov for NCT numbers.
7. **Author output check**, for entries still missing: search the first author's name
   alone. A prolific real author with no work resembling the cited title is meaningful;
   an author with no indexed output at all is not — they may simply not be indexed.

`scripts/check_dois.py` batches step 1 over a whole list in one go; use it when there are
more than a handful of DOIs.
`scripts/check_titles.py` runs steps 2-4 for entries that have no DOI: it searches Crossref and
OpenAlex by title and compares first author, year and journal. Its `FOUND_DIFFERS` is evidence
of a mis-citation; its `NOT FOUND`, `AMBIGUOUS` and `FOUND_REVIEW` are not verdicts, so carry on
with the steps above for those.

**Tooling.** These are all open HTTP APIs, callable with `curl` or WebFetch and needing
no key. If the environment happens to expose literature-search MCP tools (OpenAlex,
PubMed, CORE and similar wrappers), prefer them — they are faster and quota-friendlier —
but the skill must work without them, and the direct calls are the reference
implementation.

**Do not let a tool outage read as absence.** If a backend errors, returns an empty
envelope, or rate-limits, retry it or fall back to another source. If a source genuinely
cannot be reached, say so in the report and mark affected entries unverifiable — never
score them as fabricated.

This rule is easy to state and easy to break, so enforce it mechanically:

- **Run a control query.** Before treating any empty result as evidence, query something
  you know exists — `New England Journal of Medicine` for a journal check, a DOI you have
  already resolved for a DOI check. If the control comes back empty, the API is failing,
  not the reference. Re-run the control every 20 or so lookups on a long list.
- **Rate limits arrive exactly when it matters.** OpenAlex starts returning HTTP 429
  partway through a large bibliography — the moment you are making the most verdicts.
  Sleep at least a second between calls, honour `Retry-After`, and back off on 429 and
  5xx. In one run at four requests per second, checking a real thesis, every journal from
  the *New England Journal of Medicine* down came back "not found".
- **Never let an exception handler return an empty list.** A caught error and a genuine
  zero-result must be distinguishable at the call site, or "the request failed" silently
  becomes "the work does not exist".

## Step 3 — Compare, don't just match

A hit is the start of the check, not the end. Against the record you found, compare:
authors (all of them, and their order), year, title wording, journal, volume, issue,
page range, and DOI.

Two mismatches matter especially:

- **DOI resolves, but to a different paper.** A real DOI grafted onto a plausible title
  is a hallmark of generated citations.
- **Real paper, wrong metadata.** Year off by a year or two, wrong journal, invented page
  range. Often a genuine citation-manager artefact rather than fabrication — say which
  you think it is, and why.

Also check `is_retracted` on the OpenAlex record. Citing a retracted paper is not
fabrication, but the author needs to know.

## Step 4 — Assign a verdict

Use `references/red-flags.md` for the full rubric and the signal catalogue. In short:

| Verdict | Meaning |
|---|---|
| **VERIFIED** | Found; key fields match. |
| **REAL BUT MIS-CITED** | The work exists; the citation gets details wrong. Say which. |
| **UNVERIFIABLE** | Not found, but it is a type these indexes cover poorly. Needs a human check. |
| **LIKELY FABRICATED** | Not found, *and* it is a type that should be indexed, *and* corroborating searches came back empty. |
| **CONFIRMED FABRICATED** | Reserved for the airtight case: DOI unregistered, no record in any source, indexed type, and the named authors have no such work. |

Anything above UNVERIFIABLE requires you to state the evidence, not just the label.

## Step 5 — Report

Lead with the counts: *N verified, N mis-cited, N unverifiable, N likely fabricated.*

Then a table with one row per reference: number, short cite, verdict, and the evidence in
a few words ("DOI 10.1234/x unregistered; no title match in Crossref/OpenAlex/Europe PMC").

Then a detail block for every entry that is **not** VERIFIED, giving:
- the citation as supplied
- what was searched, and in which sources
- what was found, with a DOI or URL the user can click
- the corrected citation, where a real work was identified
- for fabrication calls, an explicit statement of what would change the verdict

Close with what you could **not** check and why — the honest boundary of the audit.

If the list is long (roughly 25+) or the user wants something to circulate, offer the
report as a document or artifact rather than terminal output.

## Tone

The user may have written these references themselves, or may be checking someone else's
work — a student's, a job applicant's, a co-author's. Report findings flatly and let them
draw the conclusion. Do not speculate about intent, and do not use "AI-generated" as an
accusation when "not found in any index I searched" is the actual finding.
