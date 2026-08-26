# Lookup sources, calls, and quirks

Every source here is a free, open, keyless HTTP API. Call them with `curl`, WebFetch, or
whatever the environment provides. If literature-search MCP tools are connected, prefer
them — but these calls are the reference implementation and the guaranteed path.

**Contact email.** OpenAlex, Crossref and Unpaywall offer a faster "polite pool" to
callers who identify themselves via `mailto=`. Use the user's email if they have given
one, or `git config user.email` if set. If you have neither, omit the parameter — the
calls still work, just on the common pool. Never invent an address.

## DOI existence — the strongest single test

Content negotiation against doi.org. Registered DOIs return CSL JSON; unregistered ones
404. This is the check that catches invented DOIs.

```bash
curl -sIL -o /dev/null -w '%{http_code}\n' "https://doi.org/<DOI>"
curl -sL -H "Accept: application/vnd.citationstyles.csl+json" "https://doi.org/<DOI>"
```

Crossref gives richer metadata and an explicit 404:

```bash
curl -s "https://api.crossref.org/works/<DOI>"
```

Read the returned `title`, `author`, `container-title`, `issued`, `volume`, `page` and
compare them to the citation. **A 200 is not a pass** — the DOI may resolve to an
entirely different paper than the one cited.

DataCite handles datasets, software and many theses that Crossref does not:

```bash
curl -s "https://api.datacite.org/dois/<DOI>"
```

Prefix sanity: the registrant prefix (`10.1038`, `10.1016`, …) is worth a glance. A
prefix belonging to a different publisher than the cited journal is a red flag; an
unallocated prefix is close to conclusive. Check one with
`curl -s "https://api.crossref.org/prefixes/10.1038"`.

`scripts/check_dois.py` runs all of the above over a list of DOIs in one pass.

## Crossref — title and author search

```bash
curl -s "https://api.crossref.org/works?query.bibliographic=<full+citation>&rows=5"
curl -s "https://api.crossref.org/works?query.title=<title>&rows=5"
```

`query.bibliographic` takes a whole messy citation string and is often the fastest way to
find a real paper behind a garbled reference. Check the `score` — Crossref always returns
*something*, so a low-scoring top hit whose title bears no resemblance is a miss, not a
match.

## OpenAlex — broadest coverage, all disciplines

```bash
curl -s "https://api.openalex.org/works?filter=doi:<DOI>"
curl -s "https://api.openalex.org/works?filter=title.search:<words>"
curl -s "https://api.openalex.org/works?search=<phrase>"
curl -s "https://api.openalex.org/authors?search=<author+name>"
```

Useful fields on a work: `display_name`, `authorships`, `publication_year`,
`primary_location.source.display_name`, `biblio.{volume,issue,first_page,last_page}`,
`ids.doi`, **`is_retracted`**, `type`.

`title.search` is stricter than `search`; try both before concluding nothing is there.
Roughly 100k calls/day, no key.

## Europe PMC — biomedical (PubMed content and more)

```bash
curl -s 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=TITLE_ABS%3A%22<title>%22&format=json'
curl -s 'https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI%3A%22<DOI>%22&format=json'
```

Add `AND SRC:MED` to restrict to genuine PubMed-indexed content. Preferred over NCBI
E-utilities, which needs two round trips and returns abstracts only as XML.

Three traps:
- Europe PMC searches the **full text** of open-access papers by default, so scope
  keyword queries to `TITLE_ABS:`. Otherwise an incidental mention inside someone else's
  paper matches, and citation-sorting can float it to the top.
- An unrecognised field name returns **0 hits rather than an error** — a typo looks
  exactly like a genuine absence. Sanity-check a suspicious zero with a query you know
  should hit.
- If the response comes back as bare `{"version":"..."}` with no `hitCount`, the service
  is degraded, not empty. Never read that as "reference not found".

## CORE — theses, repositories, reports, grey literature

```bash
curl -s "https://api.core.ac.uk/v3/search/works?q=<query>&limit=10"
```

The legitimate Google Scholar substitute, and the right place to check a dissertation or
institutional report before calling it fake. An API key is optional and only raises the
anonymous rate limit. Quirks: a bare multi-word query in parentheses returns 0 hits
(parentheses are only valid after a field prefix), and bare terms are OR-ed, so AND them
explicitly. Its `documentType` and `_exists_:fullText` filters are advertised but broken.

## ClinicalTrials.gov — NCT numbers

```bash
curl -s "https://clinicaltrials.gov/api/v2/studies/NCT01234567"
```

An NCT number either exists or does not; no ambiguity to manage.

## Unpaywall — open-access copies, and a second DOI check

```bash
curl -s "https://api.unpaywall.org/v2/<DOI>?email=<email>"
```

Requires an email parameter but no account. Useful for handing the user a readable copy
of a paper you have just confirmed.

## Books, chapters, standards

Not covered by the above:

```bash
curl -s "https://openlibrary.org/search.json?q=<title>"
curl -s "https://www.googleapis.com/books/v1/volumes?q=intitle:<title>"
```

An ISBN with a bad check digit is a strong fabrication signal. A book absent from these
is not — mark it UNVERIFIABLE and point the user at WorldCat or a library catalogue.

## Not used

**Google Scholar** has no public API, serves CAPTCHAs, and forbids scraping in its terms.
Do not scrape it, and do not tell the user a reference is fake on the grounds that it is
missing from a source you never queried.
