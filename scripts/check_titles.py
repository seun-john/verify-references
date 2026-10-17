#!/usr/bin/env python3
"""Look up references that have no DOI by title, and compare what is found with the citation.

check_dois.py needs a DOI and check_books.py only covers books. An article without a DOI,
a report, a thesis or a conference paper had no script at all. This one searches Crossref and
then OpenAlex by title (and the first author's surname), and for the best hit compares the
title, first author, year and (for journal articles) the journal with the citation.

It reports what it found, never a guess:

    FOUND           a record with the same title exists and the first author, year and journal
                    agree with the citation
    FOUND_DIFFERS   a record with the same title exists but something the citation says
                    disagrees with it (the "differences" list says what)
    NOT FOUND       no record with a close title in either index. This is NOT evidence of
                    fabrication: open indexes miss books, theses, reports, pre-1970 work and
                    much else. Treat it as "look elsewhere".
    FOUND_REVIEW    a record with the same title and first author exists, but the year of a book
                    or chapter differs, which editions and reprints explain as often as an error
    AMBIGUOUS       several different works share the title and none is by the first author
                    cited, so the match cannot be attributed to the work cited
    NETWORK ERROR   a request failed. Never evidence of anything.

A title match is accepted only when the title is very close, so a famous title shared by two
different works can still come back FOUND for the wrong work; the record that was matched is
always shown so you can see which one.

Usage:
    python check_titles.py --file references.txt
    python check_titles.py "Hardin, G. (1968). The tragedy of the commons. Science, 162, 1243-1248."
    cat refs.txt | python check_titles.py --json

Options:
    --all           also look up entries that carry a DOI (default: only entries without one)
    --json          machine-readable output
    --min-coverage PCT  exit 3 if fewer than PCT percent of the entries were decided
    --delay SECS    pause between entries (default 0.4)

Standard library only. No API key needed.
"""

import argparse
import difflib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

UA = "verify-references/1.0 (citation verification)"
CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
MATCH_THRESHOLD = 0.85
MIN_TITLE_CHARS = 12

# A control the sources must answer, or their silence proves nothing.
CONTROL = {"title": "The tragedy of the commons", "surname": "Hardin", "year": 1968}

DASH = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
                      "­": "", "​": ""})
STOP = {"of", "the", "and", "for", "in", "on", "a", "an", "de", "la", "to", "at", "by"}


def fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text)).strip()


def tokens(text):
    return [t for t in fold(text).split() if t not in STOP]


def main_title(title):
    """The title before a subtitle separator (a colon or a spaced dash)."""
    return re.split(r"\s*:\s*|\s+-\s+", title or "", maxsplit=1)[0]


def title_score(cited, record):
    """1.0 for the same title. Titles that differ only in the subtitle still count when the
    main title has at least three meaningful words, so short generic titles cannot match."""
    a, b = fold(cited), fold(record)
    if not a or not b:
        return 0.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    main_a, main_b = main_title(cited), main_title(record)
    if len(tokens(main_a)) >= 3 and fold(main_a) == fold(main_b):
        return max(score, 0.9)
    ta, tb = set(tokens(cited)), set(tokens(record))
    if ta and tb and len(ta & tb) / len(ta | tb) < 0.8:
        score = min(score, 0.8)  # an extra word or two is a different title
    return score


def same_journal(cited, record):
    a = [t for t in tokens(cited) if len(t) > 1]  # drop stray initials such as "U S A"
    b = tokens(record)
    if not a or not b or a == b:
        return True
    ja, jb = " ".join(a), " ".join(b)
    if ja in jb or jb in ja:
        return True
    pos = matched = 0
    for t in a:  # abbreviation: each cited word starts the next matching record word
        k = pos
        while k < len(b) and not b[k].startswith(t[: max(1, min(len(t), 3))]):
            k += 1
        if k < len(b):
            matched += 1
            pos = k + 1
    if matched / len(a) >= 0.75:
        return True
    return len(set(a) & set(b)) / len(set(a) | set(b)) >= 0.5


_GENERIC_INSTITUTION = {"university", "college", "institute", "school", "research", "archive",
                        "repository", "library", "digital", "department", "faculty", "thesis"}
_BOOK_TYPES = {"book", "monograph", "edited-book", "reference-book", "book-chapter",
               "book-section", "book-part"}


def same_institution(cited, record):
    """For theses: does the institution in the citation appear in the record's repository
    name? Only judged when the record names an institution at all."""
    rec = tokens(record)
    if not any(t in ("university", "college", "institute", "universiteit", "universite") for t in rec):
        return True
    wanted = [t for t in tokens(cited) if t not in _GENERIC_INSTITUTION]
    return not wanted or bool(set(wanted) & set(rec))


def parse_entry(line):
    """Pull the first author's surname, year, title and the text after the title out of an
    APA-like entry. Fields it cannot find are None."""
    text = line.translate(DASH).strip()
    text = re.sub(r"\s+", " ", text)
    doi = DOI_RE.search(text)
    year = re.search(r"\((n\.d\.|\d{4})[a-z]?\)", text)
    surname = None
    title = rest = None
    if year:
        lead = text[: year.start()].strip()
        m = re.match(r"^([^,(]+?),\s", lead + " ")
        if m and len(m.group(1).split()) <= 3:
            surname = m.group(1).strip()
        after = text[year.end():].lstrip(" .,:;")
        m = re.match(r"(?P<t>.+?[.?!])(?:\s+(?P<r>.*))?$", after)
        # do not end a title at an initial such as "U.S."
        if m:
            end = m.end("t")
            while end < len(after) and re.search(r"(?:^|[\s.])[A-Z]\.$", after[:end]) and end < len(after):
                nxt = re.search(r"[.?!](?=\s|$)", after[end:])
                if not nxt:
                    break
                end += nxt.end()
            title = after[:end].rstrip(".")
            rest = after[end:].strip() or None
        else:
            title = after.rstrip(".")
    return {
        "raw": line.strip(),
        "surname": surname,
        "year": None if not year or year.group(1) == "n.d." else int(year.group(1)),
        "title": title,
        "rest": rest,
        "has_doi": bool(doi),
    }


def fetch(url, tries=3):
    """Returns (data, ok). ok=False means the request failed -- never 'not found'."""
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace")), True
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                wait = e.headers.get("Retry-After") if e.headers else None
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = 2.0 * (2 ** attempt)
                if wait > 60:  # a daily budget is spent: waiting here would hang the run
                    return None, False
                time.sleep(min(wait, 20.0))
                continue
            return None, False
        except Exception:
            if attempt < tries - 1:
                time.sleep(2.0 * (2 ** attempt))
                continue
            return None, False
    return None, False


def clean(value):
    return re.sub(r"<[^>]+>", "", html.unescape(value or "")).strip()


def crossref_search(title, surname):
    query = {"query.bibliographic": title, "rows": "5",
             "select": "title,author,issued,published-print,published-online,container-title,type,DOI"}
    if surname:
        query["query.author"] = surname
    data, ok = fetch(CROSSREF + "?" + urllib.parse.urlencode(query))
    if not ok or not isinstance(data, dict):
        return None
    out = []
    for item in (data.get("message") or {}).get("items", []):
        years = set()
        for key in ("issued", "published-print", "published-online"):
            parts = (item.get(key) or {}).get("date-parts") or [[None]]
            if parts[0] and parts[0][0]:
                years.add(int(parts[0][0]))
        authors = item.get("author") or []
        out.append({
            "source": "Crossref",
            "title": clean((item.get("title") or [""])[0]),
            "families": [clean(a.get("family") or a.get("name") or "") for a in authors],
            "years": sorted(years),
            "container": clean((item.get("container-title") or [""])[0]),
            "type": item.get("type"),
            "doi": item.get("DOI"),
        })
    return out


def openalex_search(title, surname):
    query = {"search": title, "per-page": "5",
             "select": "display_name,authorships,publication_year,primary_location,type,doi"}
    data, ok = fetch(OPENALEX + "?" + urllib.parse.urlencode(query))
    if not ok or not isinstance(data, dict):
        return None
    out = []
    for item in data.get("results", []):
        families = []
        for a in item.get("authorships") or []:
            name = (a.get("author") or {}).get("display_name") or ""
            families.append(name.split()[-1] if name else "")
        source = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
        year = item.get("publication_year")
        out.append({
            "source": "OpenAlex",
            "title": clean(item.get("display_name")),
            "families": families,
            "years": [int(year)] if year else [],
            "container": clean(source),
            "type": item.get("type"),
            "doi": item.get("doi"),
        })
    return out


SOURCES = [crossref_search, openalex_search]


def cited_is_journal_article(cited):
    """A citation with volume or page numbers is for a journal article; a bare publisher or
    institution is for a book, report or thesis."""
    return bool(re.search(r"\d", cited["rest"] or ""))


_JOURNAL_TYPES = ("journal-article", "article")


def compatible(cited, record):
    """A citation that names only a publisher or institution is for a book, report or thesis.
    An article, chapter or conference paper that shares its title is a different work (a thesis
    and the paper made from it, or a book and a chapter, often do)."""
    if cited_is_journal_article(cited):
        return True
    return record.get("type") not in (*_JOURNAL_TYPES, "proceedings-article", "conference-paper",
                                      "book-chapter", "book-section", "book-part", "posted-content",
                                      "reference-entry")


def compare(cited, record):
    """(differences, review) between the citation and a record.

    `differences` are fields that disagree and can be trusted to: first author, the year of
    anything but a book, the journal of an article, the institution of a thesis. `review`
    lists the year of a book or chapter, which differs between editions and reprints, so a
    disagreement there is not a finding. Fields either side lacks are not compared."""
    differences, review = [], []
    families = [fold(f) for f in record["families"] if f]
    if cited["surname"] and families and fold(cited["surname"]).split()[-1:] != families[0].split()[-1:]:
        differences.append("first author")
    if cited["year"] and record["years"] and cited["year"] not in record["years"]:
        (review if record.get("type") in _BOOK_TYPES else differences).append("year")
    rest = cited["rest"] or ""
    if record.get("type") in _JOURNAL_TYPES and record["container"] and cited_is_journal_article(cited):
        if not same_journal(rest.split(",")[0], record["container"]):
            differences.append("journal")
    if record.get("type") in ("dissertation", "thesis") and record["container"] and rest:
        if not same_institution(rest, record["container"]):
            differences.append("institution")
    return differences, review


def first_author_of(record):
    families = [fold(f) for f in record["families"] if f]
    return families[0].split()[-1] if families and families[0].split() else None


def pick(cited, candidates):
    """The best close-title candidate, preferring the one the citation agrees with most.

    Returns (record, differences, review, score), the string "AMBIGUOUS" when several works share the
    title and none of them is by the cited first author, or None when nothing is close."""
    close = []
    for rec in candidates:
        score = title_score(cited["title"], rec["title"])
        if score >= MATCH_THRESHOLD and compatible(cited, rec):
            diffs, review = compare(cited, rec)
            close.append((len(diffs), len(review), -score, rec, score))
    if not close:
        return None
    close.sort(key=lambda c: c[:3])
    n_diffs, _, _, rec, score = close[0]
    if n_diffs and cited["surname"]:
        firsts = {first_author_of(c[3]) for c in close if first_author_of(c[3])}
        if len(firsts) > 1:
            return "AMBIGUOUS"
    diffs, review = compare(cited, rec)
    return rec, diffs, review, score


def check(cited, searches=None):
    """Look one parsed entry up in every index. Returns a result dict with a `status`."""
    searches = searches or SOURCES
    result = {"cited": cited}
    if not cited["title"] or len(cited["title"]) < MIN_TITLE_CHARS:
        result.update(status="NOT CHECKED", reason="no usable title")
        return result
    answered, pool, failed = 0, [], []
    for search in searches:
        candidates = search(cited["title"], cited["surname"])
        if candidates is None:
            failed.append(search.__name__)
        else:
            answered += 1
            pool.extend(candidates)
    if failed:
        result["sources_failed"] = failed
    if not answered:
        result["status"] = "NETWORK ERROR"
        return result
    found = pick(cited, pool)
    if found == "AMBIGUOUS":
        result["status"] = "AMBIGUOUS"
    elif found:
        rec, diffs, review, score = found
        result.update(
            status="FOUND_DIFFERS" if diffs else "FOUND_REVIEW" if review else "FOUND",
            differences=diffs,
            review=review,
            title_similarity=round(score, 3),
            match={k: rec[k] for k in ("source", "title", "families", "years", "container", "type", "doi")},
        )
    else:
        result["status"] = "NOT FOUND"
    return result


def controls(searches=None):
    """Which sources can find the control reference at all."""
    live = {}
    for search in searches or SOURCES:
        cands = search(CONTROL["title"], CONTROL["surname"])
        live[search.__name__] = bool(cands) and any(
            title_score(CONTROL["title"], c["title"]) >= MATCH_THRESHOLD for c in cands)
    return live


def coverage_block(rows):
    """Decided = a record was found (FOUND or FOUND_DIFFERS). NOT FOUND, AMBIGUOUS, NETWORK ERROR and
    NOT CHECKED are undecided: absence from an open index is not a finding."""
    reasons = {}
    for r in rows:
        key = {"NOT FOUND": "not_in_index", "AMBIGUOUS": "ambiguous_title",
               "FOUND_REVIEW": "year_may_be_an_edition",
               "NETWORK ERROR": "network_error", "NOT CHECKED": "no_usable_title"}.get(r["status"])
        if key:
            reasons[key] = reasons.get(key, 0) + 1
    undecided = sum(reasons.values())
    return {"unit": "references", "items": len(rows), "decided": len(rows) - undecided,
            "undecided": undecided, "reasons": dict(sorted(reasons.items())), "suppressed": 0,
            "notes": ["not_in_index means no close title in Crossref or OpenAlex; it is not "
                      "evidence that the reference is invented"]}


def describe_coverage(block):
    text = "decided %d of %d %s" % (block["decided"], block["items"], block["unit"])
    if block["undecided"]:
        why = ", ".join("%s %d" % (k, v) for k, v in
                        sorted(block["reasons"].items(), key=lambda kv: -kv[1]))
        text += "; %d could not be checked (%s)" % (block["undecided"], why)
    return text


def decided_share(block):
    return round(100.0 * block["decided"] / block["items"], 1) if block["items"] else None


def render(rows, live):
    for r in rows:
        c = r["cited"]
        mark = {"FOUND": "ok  ", "FOUND_DIFFERS": "DIFF", "NOT FOUND": "?   ", "AMBIGUOUS": "?   ", "FOUND_REVIEW": "?   ",
                "NETWORK ERROR": "err ", "NOT CHECKED": "-   "}[r["status"]]
        print(f"{mark} {r['status']}: {c['raw'][:100]}")
        if r.get("sources_failed"):
            print("     did not answer: " + ", ".join(r["sources_failed"]))
        if r.get("match"):
            m = r["match"]
            first = m["families"][0] if m["families"] else "?"
            print(f"     {m['title']}")
            print(f"     {first} | {m['container'] or m['type']} | {','.join(map(str, m['years']))} | {m['source']}")
            if r["differences"]:
                print("     differs from the citation in: " + ", ".join(r["differences"]))
            if r.get("review"):
                print("     " + ", ".join(r["review"]) + " differs, but books are reprinted and re-edited: check the edition")
        print()
    if not all(live.values()):
        down = ", ".join(k for k, v in live.items() if not v)
        print(f"-- control query failed for: {down}; their silence is not evidence.")
    print("NOT FOUND is a prompt to look elsewhere, not a verdict. Open indexes miss books,")
    print("theses, reports, pre-1970 work and much non-English work.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("refs", nargs="*", help="references to check")
    ap.add_argument("--file", help="file with one reference per line")
    ap.add_argument("--all", action="store_true", help="also check entries that carry a DOI")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--min-coverage", type=float, metavar="PCT",
                    help="exit 3 if fewer than PCT percent of the entries were decided")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between entries")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    lines = list(args.refs)
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            lines += fh.read().splitlines()
    if not lines and not sys.stdin.isatty():
        lines += sys.stdin.read().splitlines()
    entries = [parse_entry(l) for l in lines if len(l.strip()) >= 30]
    if not args.all:
        entries = [e for e in entries if not e["has_doi"]]
    if not entries:
        sys.exit("No references to check. Entries with a DOI are skipped unless --all is given.")

    live = controls()
    if not any(live.values()):
        sys.exit("Every index failed its control query. Aborting rather than reporting false "
                 "absences.")
    active = [s for s in SOURCES if live.get(s.__name__)]

    rows = []
    for i, entry in enumerate(entries):
        rows.append(check(entry, active))
        if i + 1 < len(entries):
            time.sleep(args.delay)

    block = coverage_block(rows)
    if args.json:
        json.dump({"sources_live": live, "coverage": block, "results": rows}, sys.stdout,
                  indent=2, ensure_ascii=False)
        print()
        print("coverage: " + describe_coverage(block), file=sys.stderr)
    else:
        render(rows, live)
        print("\nCoverage: " + describe_coverage(block))
    share = decided_share(block)
    if args.min_coverage is not None and (share is None or share < args.min_coverage):
        print("Coverage is below --min-coverage %g." % args.min_coverage, file=sys.stderr)
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
