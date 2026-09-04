# verify-references

A Claude skill that checks whether the citations in a bibliography actually exist — and
flags the ones that were invented, whether by a language model or by a bad night with a
reference manager.

Fabricated citations are the most common serious failure in AI-assisted writing. They are
also the hardest to spot by eye, because a generated reference is *designed* to look
plausible: real authors, a real journal, a well-formed DOI, a title that fits the claim a
little too neatly. The only reliable test is to look every one of them up.

## What it does

For each reference it finds, the skill:

1. resolves the DOI against doi.org, Crossref and DataCite — an unregistered DOI is the
   strongest signal there is;
2. searches Crossref, OpenAlex, Europe PMC and CORE by exact title, distinctive phrase,
   and author + year;
3. compares the record it finds against the citation as written — authors, year, journal,
   volume, pages — because a real DOI bolted onto the wrong title is a classic tell;
4. checks whether the work has been retracted;
5. assigns one of five verdicts and shows the evidence behind it.

| Verdict | Meaning |
|---|---|
| **VERIFIED** | Found; key fields match. |
| **REAL BUT MIS-CITED** | The work exists; the citation gets details wrong. |
| **UNVERIFIABLE** | Not found, but it is a type the open indexes cover poorly. |
| **LIKELY FABRICATED** | Not found, and it is a type that *should* have been found. |
| **CONFIRMED FABRICATED** | Unregistered DOI, no record anywhere, authors have no such work. |

## The two design rules

**It never judges a reference from the model's own memory.** Recognising a title is not
evidence. Model recall is the exact mechanism that fabricates citations in the first
place, so it cannot be the thing that audits them. Every verdict rests on a lookup made
during the run, and names the source that produced it.

**"Not found" is never reported as "fake".** Open indexes miss books, chapters, theses,
government and NGO reports, standards, most pre-1970 work, much non-English work, and
many conference papers. A tool that calls a real citation fabricated does more harm than
one that misses a fake, so absence of evidence gets its own verdict — UNVERIFIABLE — and
the fabrication verdicts require positive evidence, spelled out in the report.

## Install

Clone into your personal skills directory, and it is available in every project:

```bash
git clone https://github.com/<you>/verify-references ~/.claude/skills/verify-references
```

Or into a single project, to share it with a repo via version control:

```bash
git clone https://github.com/<you>/verify-references .claude/skills/verify-references
```

Claude Code picks it up on the next session. Nothing else to configure: every data source
is a free, keyless, open API.

## Use

Just ask, in whatever words come naturally:

```
check whether these references are real
are any of these citations made up?
verify the bibliography in thesis-draft.docx
/verify-references
```

Hand it a pasted list, a `.bib` or `.ris` file, or a whole manuscript. Given a manuscript
it also checks whether each source actually supports the sentence citing it — a real
paper cited for something it never said is its own kind of problem.

### The bundled scripts

Both run standalone, without Claude in the loop.

```bash
python scripts/check_dois.py --file bibliography.txt
```

Scrapes DOIs out of prose, so you can pipe a whole reference list at it. Exit code 1 if
any DOI is unregistered, which makes it usable as a pre-submission check in CI.

```bash
python scripts/check_books.py --file bibliography.txt
```

Picks the book-like entries out of a reference list and checks them against Open Library
and Crossref's monograph index. Books are the blind spot in citation checking — Crossref
and PubMed barely carry them, so a journal-only checker reports even Bronfenbrenner's
*The ecology of human development* as missing. Matching requires the author's surname on
the catalogue record, and tolerates the subtitle and edition-year drift that breaks naive
title comparison.

## Sources

Crossref · OpenAlex · DataCite · Europe PMC (PubMed content) · CORE · Open Library ·
ClinicalTrials.gov · Unpaywall · Google Books

All free and open. No key required for any of them. Google Scholar is deliberately not
used: it has no public API and forbids scraping.

If your environment has literature-search MCP tools connected, the skill will prefer them
for speed, but it never depends on them.

## Limits

Worth being honest about:

- It confirms that a work **exists** and that a citation **describes it correctly**. It
  does not assess whether the work is any good, or whether the field agrees with it.
- Coverage is the coverage of open metadata. Books, chapters, standards, legal and
  regional-language sources land in UNVERIFIABLE more often than they should.
- Claim-checking against a manuscript needs the full text to be reachable. Behind a
  paywall, it can compare against the abstract only, and will say so.
- It reports evidence, not intent. "Not found in any index searched" is a finding;
  "written by AI" is a conclusion for a human to draw.

## Contributing

Issues and PRs welcome — particularly new sources for badly-covered material (books,
non-English journals, regional indexes) and real-world cases where the rubric got a
verdict wrong. A false accusation against a genuine citation is the highest-priority bug
in this repo.

## Licence

MIT. See [LICENSE](LICENSE).
