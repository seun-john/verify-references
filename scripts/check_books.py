#!/usr/bin/env python3
"""Check whether cited books and monographs actually exist.

Books are the blind spot in citation checking. Crossref and PubMed barely carry
them, so a bibliography's books come back "not found" no matter how famous they
are -- and a checker that treats that as evidence will call Bronfenbrenner's
"The ecology of human development" a fabrication. This script closes that gap by
querying catalogues that do hold books.

Sources, in the order tried:
    Open Library  -- the Internet Archive's catalogue. Broad, keyless, reliable.
    Crossref      -- filtered to monograph/book/edited-book; holds mostly recent
                     academic books with DOIs.
    Google Books  -- opportunistic only; it rate-limits hard without a key.

Matching is deliberately strict. Open Library returns hundreds of loose hits for
any common phrase, so a hit counts only when the title substantially matches AND
the cited author's surname appears on the record. Edition years drift, so the
year is a supporting signal, never a requirement.

Usage:
    python check_books.py --file references.txt
    python check_books.py "Bronfenbrenner, U. (1979). The ecology of human development. Harvard University Press."
    cat refs.txt | python check_books.py --json

Standard library only. No API key needed.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "verify-references/1.0 (citation verification)"
OL = "https://openlibrary.org/search.json"
XR = "https://api.crossref.org/works"
GB = "https://www.googleapis.com/books/v1/volumes"

# Bronfenbrenner 1979 -- in every catalogue worth querying. If a source cannot
# find this, the source is broken and its silence proves nothing.
#
# The control carries its full subtitle on purpose. Catalogues hold the short
# form, so this probe exercises the subtitle-mismatch path that a naive title
# comparison fails. A control that is easier than the real queries certifies
# nothing.
CONTROL_TITLE = "The ecology of human development: Experiments by nature and design"
CONTROL_AUTHOR = "Bronfenbrenner"

DASH = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-",
                      "—": "-", "−": "-", "­": "", "​": ""})

# "(3rd ed.)", a university press, a publisher city -- the marks of a book
BOOK_CUES = re.compile(
    r"\(\d+(?:st|nd|rd|th)\s+ed\.\)|\bUniversity Press\b|\bPress\b|\bPublish\w*\b"
    r"|\bRoutledge\b|\bSage\b|\bWiley\b|\bPalgrave\b|\bMacmillan\b|\bPearson\b"
    r"|\bHarper\w*\b|\bPenguin\b|\bElsevier\b|\bBlackwell\b|\bOxford\b|\bCambridge\b",
    re.I,
)
ENTRY = re.compile(r"^(?:[A-Z][\wÀ-ſ'’.\-]+.{0,150}?)\((?:n\.d\.|\d{4}[a-z]?)\)")


def fetch(url, tries=4):
    """Returns (data, ok). ok=False means the REQUEST failed -- never 'not found'."""
    for attempt in range(tries):
        req = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": UA})
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
                time.sleep(min(wait, 30.0))
                continue
            return None, False
        except Exception:
            if attempt < tries - 1:
                time.sleep(2.0 * (2 ** attempt))
                continue
            return None, False
    return None, False


def toks(s):
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


def overlap(a, b):
    """Symmetric containment, not one-directional coverage.

    Catalogues routinely record the short title while the citation carries the
    full subtitle -- Open Library holds Bronfenbrenner as "The ecology of human
    development", cited as "...: Experiments by nature and design". Measuring
    only what fraction of the CITED title was matched scores that 0.5 and throws
    away a correct hit. Containment in either direction is the right test; the
    shorter side must still carry enough words to mean something.
    """
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    common = len(ta & tb)
    scores = [common / len(ta)]
    if len(tb) >= 3:
        scores.append(common / len(tb))
    return max(scores)


def parse(entry):
    """Pull surname, year, title and publisher out of an APA-ish book citation."""
    e = entry.translate(DASH).strip()
    surname = re.match(r"^([A-Z][\wÀ-ſ'’\-]+)", e)
    year = re.search(r"\((n\.d\.|\d{4})[a-z]?\)", e)
    after = e[year.end():].lstrip(". ") if year else e
    # title runs to the first sentence break followed by a capital
    title = re.split(r"(?<=[a-z\)\]])\.\s+(?=[A-Z])", after)[0]
    title = re.sub(r"\s*\(\d+(?:st|nd|rd|th)\s+ed\.\)\s*", " ", title)
    pub = ""
    tail = after[len(title):]
    m = re.search(r"(?:^|\.\s*)(?:[A-Z][\w.'\- ]+:\s*)?([A-Z][\w&.'\- ]{3,60}"
                  r"(?:Press|Publishers?|Books|Routledge|Sage|Wiley|Palgrave|Macmillan))", tail)
    if m:
        pub = m.group(1).strip()
    return {
        "surname": surname.group(1) if surname else "",
        "year": None if not year or year.group(1) == "n.d." else int(year.group(1)),
        "title": re.sub(r"\s+", " ", title).strip(" .,"),
        "publisher": pub,
        "raw": e,
    }


def _match(cited, cand_title, cand_authors, cand_year):
    """Strict: substantial title overlap, plus the surname on the record."""
    ov = overlap(cited["title"], cand_title)
    if ov < 0.6:
        return None
    sur = cited["surname"].lower()
    authors = " ".join(cand_authors or []).lower()
    author_ok = bool(sur) and sur in authors
    if not author_ok and ov < 0.85:
        return None
    year_note = ""
    if cited["year"] and cand_year:
        gap = abs(cited["year"] - int(cand_year))
        if gap > 3:
            year_note = " (cited %s, catalogue %s -- edition difference?)" % (
                cited["year"], cand_year)
    return {"title": cand_title, "authors": (cand_authors or [])[:3],
            "year": cand_year, "overlap": round(ov, 2),
            "author_matched": author_ok, "note": year_note}


def try_openlibrary(cited):
    q = urllib.parse.quote(cited["title"][:180])
    url = ("%s?q=%s&limit=10&fields=title,author_name,first_publish_year,publisher"
           % (OL, q))
    d, ok = fetch(url)
    time.sleep(0.7)
    if not ok:
        return None, "openlibrary-failed"
    for doc in (d.get("docs") or []):
        m = _match(cited, doc.get("title", ""), doc.get("author_name"),
                   doc.get("first_publish_year"))
        if m:
            m["source"] = "Open Library"
            return m, "ok"
    return False, "ok"


def try_crossref(cited):
    q = urllib.parse.quote(cited["title"][:200])
    url = ("%s?query.bibliographic=%s&filter=type:monograph,type:book,"
           "type:edited-book,type:book-chapter&rows=6" % (XR, q))
    d, ok = fetch(url)
    time.sleep(0.6)
    if not ok:
        return None, "crossref-failed"
    for it in (d.get("message", {}).get("items") or []):
        names = [" ".join(x for x in (a.get("given"), a.get("family")) if x)
                 for a in it.get("author", [])]
        yr = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
        m = _match(cited, (it.get("title") or [""])[0], names, yr)
        if m:
            m["source"] = "Crossref"
            m["doi"] = it.get("DOI")
            return m, "ok"
    return False, "ok"


def try_googlebooks(cited):
    q = urllib.parse.quote('intitle:"%s"' % cited["title"][:120].replace('"', ""))
    d, ok = fetch("%s?q=%s&maxResults=6" % (GB, q), tries=1)
    time.sleep(0.5)
    if not ok:
        return None, "googlebooks-unavailable"
    for it in (d.get("items") or []):
        v = it.get("volumeInfo", {})
        yr = (v.get("publishedDate") or "")[:4]
        m = _match(cited, v.get("title", ""), v.get("authors"),
                   int(yr) if yr.isdigit() else None)
        if m:
            m["source"] = "Google Books"
            return m, "ok"
    return False, "ok"


def self_test():
    """Check the matcher before trusting it, with no network involved.

    Catalogues hold short titles; citations carry subtitles. If containment
    matching regresses, every book with a subtitle silently becomes a miss --
    so this asserts the exact pair that once broke.
    """
    cited = "The ecology of human development: Experiments by nature and design"
    if overlap(cited, "The ecology of human development") < 0.9:
        return False
    # and it must still reject something genuinely unrelated
    return overlap(cited, "Recovery from childhood sexual trauma") < 0.6


def controls():
    """Which sources are answering right now.

    Liveness only -- deliberately NOT 'can it find a particular book'. Coverage
    differs per source: Crossref holds almost nothing published before DOIs, so
    probing it with a 1979 monograph marks a perfectly healthy source dead and
    silently drops it from every subsequent lookup. The control's job is to tell
    'the API is down' apart from 'the book is not there', nothing more.
    """
    probes = {
        "Open Library": (OL + "?q=" + urllib.parse.quote(CONTROL_AUTHOR) +
                         "&limit=1&fields=title", lambda d: bool(d.get("docs"))),
        "Crossref": (XR + "?filter=type:monograph&rows=1",
                     lambda d: bool((d.get("message") or {}).get("items"))),
        "Google Books": (GB + "?q=" + urllib.parse.quote("intitle:sociology") +
                         "&maxResults=1", lambda d: d.get("totalItems", 0) > 0),
    }
    live = {}
    for name, (url, ok_fn) in probes.items():
        d, ok = fetch(url, tries=2)
        live[name] = bool(ok and d and ok_fn(d))
        time.sleep(0.4)
    return live


def check(cited, live):
    tried, failed = [], []
    for name, fn in (("Open Library", try_openlibrary),
                     ("Crossref", try_crossref),
                     ("Google Books", try_googlebooks)):
        if not live.get(name):
            continue
        tried.append(name)
        res, status = fn(cited)
        if res is None:
            failed.append(name)
            continue
        if res:
            return {"status": "FOUND", "match": res, "searched": tried}
    if not tried or len(failed) == len(tried):
        return {"status": "LOOKUP FAILED", "match": None, "searched": tried}
    return {"status": "NOT IN CATALOGUES", "match": None, "searched": tried}


def render(rows, live):
    up = [k for k, v in live.items() if v] or ["NONE"]
    print("catalogues answering: " + ", ".join(up))
    down = [k for k, v in live.items() if not v]
    if down:
        print("unavailable this run: " + ", ".join(down))
    print()
    counts = {}
    for r in rows:
        st = r["res"]["status"]
        counts[st] = counts.get(st, 0) + 1
        mark = {"FOUND": "ok  ", "NOT IN CATALOGUES": "MISS",
                "LOOKUP FAILED": "err "}[st]
        c = r["cited"]
        print("%s %s (%s)" % (mark, c["title"][:74], c["year"] or "n.d."))
        m = r["res"]["match"]
        if m:
            who = ", ".join(m["authors"]) or "?"
            print("       %s | %s | %s%s" % (who[:56], m["year"], m["source"], m["note"]))
        elif st == "NOT IN CATALOGUES":
            print("       searched: %s" % ", ".join(r["res"]["searched"]))
    print("\n-- " + ", ".join("%d %s" % (v, k.lower()) for k, v in sorted(counts.items())))
    if counts.get("NOT IN CATALOGUES"):
        print("\nNOT IN CATALOGUES is a prompt to look, not a verdict. Open Library's")
        print("coverage of African, regional and small-press publishing is thin, and")
        print("chapters are often catalogued only under the parent volume. Check the")
        print("publisher's site, WorldCat or a library catalogue before concluding.")
    if counts.get("LOOKUP FAILED"):
        print("\nLOOKUP FAILED means not checked. It is never evidence of anything.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("refs", nargs="*", help="book citations to check")
    ap.add_argument("--file", help="file of references (books are auto-detected)")
    ap.add_argument("--all", action="store_true",
                    help="check every entry, not just ones that look like books")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
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

    cands = []
    for l in lines:
        l = l.strip()
        if len(l) < 30 or not ENTRY.match(l):
            continue
        if args.all or BOOK_CUES.search(l):
            cands.append(l)
    if not cands:
        sys.exit("No book-like references found. Pass --all to check every entry.")

    if not self_test():
        sys.exit("Matcher self-test failed -- title matching is broken. Aborting "
                 "rather than reporting false absences.")
    live = controls()
    if not any(live.values()):
        sys.exit("Every book catalogue failed its control query. Aborting rather "
                 "than reporting false absences.")

    rows = []
    for raw in cands:
        cited = parse(raw)
        if len(cited["title"]) < 8:
            continue
        rows.append({"cited": cited, "res": check(cited, live)})

    if args.json:
        json.dump({"sources_live": live, "results": rows}, sys.stdout,
                  indent=2, ensure_ascii=False)
        print()
    else:
        render(rows, live)
    sys.exit(0)


if __name__ == "__main__":
    main()
