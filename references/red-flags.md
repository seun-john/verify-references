# Verdict rubric and signal catalogue

## The rubric

Work down the list; the first row that fits is the verdict.

### VERIFIED
A record was found and the key fields agree: title, first author, year (±0 — a legitimate
online-first/issue split is the one exception, note it), and journal. Give the DOI or URL.

### REAL BUT MIS-CITED
The work exists; the citation misdescribes it. Sub-types worth naming separately, because
they carry different weight:

- **Metadata drift** — wrong page range, wrong volume, year off by one, journal
  abbreviated oddly, an author dropped. Usually a reference-manager artefact, not
  fabrication. Say so.
- **Wrong DOI** — the DOI resolves to a *different* work. Strong generation signal when
  the rest of the citation is otherwise correct.
- **Wrong attribution** — right title, wrong authors, or a real paper attributed to the
  wrong journal entirely.
- **Claim mismatch** — (manuscripts only) the work is real and correctly cited, but does
  not support the sentence citing it. Report the actual finding of the paper.
- **Retracted** — flag it with the retraction notice, whatever else is true.

### UNVERIFIABLE
Nothing found, but absence here is weak evidence. Default to this verdict when the
reference is any of:

- a book, edited volume, or book chapter
- a thesis or dissertation, or an institutional/NGO/government report
- a standard, patent, legal citation, or clinical guideline
- a conference paper or abstract, especially pre-2010
- published before ~1970
- not in English, or in a regional journal with no indexed presence
- a website, blog, dataset, or piece of software
- a preprint on a server not indexed by the sources searched
- anything where a backend errored or rate-limited during the check

Say plainly what a human could do to settle it — check the publisher's site, the library
catalogue, the ISBN, the author's own page.

**Recognise this class from the citation string itself**, before any lookup. Missing
these is how a tool ends up calling a famous textbook fake:

| Cue in the citation | What it is |
|---|---|
| `(3rd ed.)`, `(8th ed.)`, a publisher name where the journal would be | a book |
| `[Master's thesis, …]`, `[Doctoral dissertation, …]` | a thesis |
| `[Working paper]`, `[Discussion paper]`, a series number | a working paper |
| A URL to an institutional domain (`unhabitat.org`, `who.int`, `worldbank.org`) | a report |
| `Cap.`, `Act`, `s.`, `v.`, a law-report citation | a statute or case |
| An organisation as author, no volume or issue | grey literature |

A reference carrying any of these gets UNVERIFIABLE on a miss, never a fabrication
verdict — the open indexes simply do not carry it. Real examples seen in one run:
Hair et al., *Multivariate Data Analysis (8th ed.)* and UN-Habitat's *World Cities
Report 2016*, both absent from Crossref and OpenAlex, both entirely real.

### LIKELY FABRICATED
All four must hold:

1. It is a journal article, post-1990, in English.
2. No record in OpenAlex, PubMed/Europe PMC, or CORE by DOI, exact title, distinctive
   phrase, or author+year.
3. The named journal exists and *is* indexed in those sources — so a real article in it
   would have been found.
4. An author-level search returns the author's genuine work but nothing resembling the
   cited title.

State all four as evidence. If any one fails, drop to UNVERIFIABLE.

### CONFIRMED FABRICATED
Everything in LIKELY FABRICATED, plus a DOI that is unregistered at doi.org and Crossref
(or no DOI at all where the journal assigns one to every article). This is as close to
proof as the method reaches.

## Signals

None of these is a verdict on its own. Several together, in the same reference or across
a list, are what make a case.

**Per reference**
- DOI 404s at doi.org, or resolves to an unrelated paper.
- DOI prefix belongs to a publisher other than the cited journal.
- Journal name is *almost* right — a real journal with a word added, dropped, or swapped
  ("Journal of Clinical Paediatrics" for "Clinical Pediatrics").
- Volume/year pairing is impossible: the journal did not exist yet, or its volume
  numbering does not reach that number in that year.
- Page range does not exist in that issue, or is suspiciously round.
- Real, prolific, topic-appropriate authors — but none of them lists this work. Generated
  citations borrow credible names.
- The title is a *perfect* restatement of the claim it is cited for. Real papers are
  rarely so obliging.
- An author list that mixes researchers who have never published together and work in
  different subfields.

**Across the list**
- Every reference lands in a handful of famous journals (Nature, Lancet, JAMA, Science)
  at a rate the topic does not justify.
- Years cluster unnaturally, or every entry is recent with no foundational older work.
- Page ranges follow a pattern (many starting at 1, or all spanning ten pages).
- Formatting is flawless and uniform in a way real hand-assembled bibliographies are not.
- Several DOIs share a prefix but have suffixes that follow no scheme that publisher uses.
- Mixed provenance: a block of solid, verifiable references followed by a block that
  verifies at a much lower rate — the signature of a real bibliography topped up.

## Things that look damning but are not

- **No DOI.** Normal for anything pre-2000, and for many humanities and regional journals.
- **Not on the publisher's site.** Journals fold, merge, and lose back catalogues.
- **Not in Google Scholar.** Not consulted here anyway — no public API, and scraping it
  breaches its terms.
- **Preprint only.** A real work that never reached a journal is still a real work.
- **Author name variants.** Transliteration, married names, initials-only, and CJK name
  ordering all break naive matching. Search variants before concluding anything.
- **Title truncated or subtitle dropped.** Search the distinctive fragment.
- **Retracted.** Real, cited, and a problem — but not fabricated.
