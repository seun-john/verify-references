#!/usr/bin/env python3
"""Batch-check DOIs for existence and pull back their real metadata.

An unregistered DOI is the strongest single signal that a citation was invented.
A registered one is only the start of the check -- compare the metadata printed
here against what the citation claims, because a real DOI attached to the wrong
title is a common fabrication pattern.

Usage:
    python check_dois.py 10.1038/nature12373 10.1016/j.cell.2020.01.001
    python check_dois.py --file refs.txt
    cat bibliography.txt | python check_dois.py          # scrapes DOIs out of prose
    python check_dois.py --file refs.txt --json > out.json

Options:
    --email ADDR   identify yourself to Crossref's polite pool (faster, optional)
    --json         machine-readable output
    --delay SECS   pause between requests (default 0.2)

Standard library only. No API key needed.
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.IGNORECASE)
TRAILING_JUNK = ".,;:)]}>\"'"

# Word autocorrects hyphens inside DOIs into en dashes, so a pasted or extracted
# reference list routinely contains "10.1007/978-3-031-34688-0" with one or more of
# those hyphens replaced. Left alone the DOI is truncated at the first non-ASCII
# dash, 404s, and gets reported as fabricated -- a false accusation against a real
# citation, which is the worst thing this tool can do. Soft hyphens (inserted by
# hyphenation) are deleted rather than replaced.
DASH_FIX = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-", "﹣": "-", "－": "-",
    "­": "", "​": "",
})
UA = "verify-references/1.0 (https://github.com/; citation verification)"


def extract_dois(text):
    """Pull DOIs out of arbitrary text, de-duplicated, order preserved."""
    text = text.translate(DASH_FIX)
    seen, out = set(), []
    for raw in DOI_RE.findall(text):
        doi = raw.rstrip(TRAILING_JUNK)
        key = doi.lower()
        if key not in seen:
            seen.add(key)
            out.append(doi)
    return out


def fetch(url, accept="application/json", tries=4):
    """GET with backoff on rate limits and server errors.

    Crucial for this tool: a 429 must never reach the caller looking like a
    "not found". Rate limits arrive exactly when a large bibliography is being
    checked, which is precisely when a wrong verdict does the most damage.
    """
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": UA})
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                wait = e.headers.get("Retry-After") if e.headers else None
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = 2.0 * (2 ** attempt)
                time.sleep(min(wait, 30.0))
                last = e.code
                continue
            return e.code, None
        except urllib.error.URLError as e:
            last = str(e.reason)
            if attempt < tries - 1:
                time.sleep(2.0 * (2 ** attempt))
                continue
            return None, {"error": last}
        except json.JSONDecodeError:
            return None, {"error": "response was not JSON"}
    return (last if isinstance(last, int) else None), None


def from_crossref(doi, email=None):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    if email:
        url += "?mailto=" + urllib.parse.quote(email)
    status, body = fetch(url)
    if status != 200 or not body:
        return status, None
    m = body.get("message", {})
    authors = [
        " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name", "")
        for a in m.get("author", [])
    ]
    # Crossref serves titles HTML-escaped ("Computers &amp; Education") and sometimes
    # wrapped in JATS markup; neither belongs in a terminal comparison.
    def clean(v):
        return re.sub(r"<[^>]+>", "", html.unescape(v)) if isinstance(v, str) else v
    issued = m.get("issued", {}).get("date-parts", [[None]])[0]
    return status, {
        "registrant": "Crossref",
        "title": clean((m.get("title") or [""])[0]),
        "authors": [clean(a) for a in authors],
        "year": issued[0] if issued else None,
        "container": clean((m.get("container-title") or [""])[0]),
        "volume": m.get("volume"),
        "issue": m.get("issue"),
        "pages": m.get("page"),
        "type": m.get("type"),
        "url": m.get("URL"),
    }


def from_datacite(doi):
    """Crossref does not register datasets, software, or many theses."""
    url = "https://api.datacite.org/dois/" + urllib.parse.quote(doi, safe="")
    status, body = fetch(url)
    if status != 200 or not body:
        return status, None
    a = body.get("data", {}).get("attributes", {})
    titles = a.get("titles") or [{}]
    return status, {
        "registrant": "DataCite",
        "title": titles[0].get("title", ""),
        "authors": [c.get("name", "") for c in a.get("creators", [])],
        "year": a.get("publicationYear"),
        "container": (a.get("publisher") or ""),
        "volume": None,
        "issue": None,
        "pages": None,
        "type": (a.get("types") or {}).get("resourceTypeGeneral"),
        "url": a.get("url"),
    }


def looks_truncated(doi):
    """A DOI cut short by line-wrapping or a copy-paste slip, not an invented one.

    Real suffixes are rarely this short. Reporting these as unregistered would
    accuse a genuine reference, so they get their own status and a prompt to
    check the source document.
    """
    suffix = doi.split("/", 1)[1] if "/" in doi else ""
    return len(suffix) < 5


def check(doi, email=None):
    status, meta = from_crossref(doi, email)
    if meta:
        return {"doi": doi, "status": "REGISTERED", "http": status, **meta}
    if status == 404:
        ds_status, ds_meta = from_datacite(doi)
        if ds_meta:
            return {"doi": doi, "status": "REGISTERED", "http": ds_status, **ds_meta}
        if ds_status == 404:
            if looks_truncated(doi):
                return {"doi": doi, "status": "TRUNCATED?", "http": 404}
            return {"doi": doi, "status": "NOT REGISTERED", "http": 404}
    if status is None:
        return {"doi": doi, "status": "NETWORK ERROR", "http": None}
    return {"doi": doi, "status": "UNCLEAR", "http": status}


def render(results):
    width = max([len(r["doi"]) for r in results] + [3])
    verdicts = {}
    for r in results:
        verdicts[r["status"]] = verdicts.get(r["status"], 0) + 1
        mark = {
            "REGISTERED": "ok  ",
            "NOT REGISTERED": "GONE",
            "TRUNCATED?": "CUT ",
            "NETWORK ERROR": "err ",
            "UNCLEAR": "?   ",
        }.get(r["status"], "?   ")
        print(f"{mark} {r['doi']:<{width}}  {r['status']}")
        if r.get("title"):
            authors = r.get("authors") or []
            shown = authors[0] if authors else "?"
            if len(authors) > 1:
                shown += f" et al. ({len(authors)} authors)"
            bits = [b for b in (r.get("container"), str(r.get("year") or "")) if b]
            print(f"     {r['title']}")
            print(f"     {shown} | {' | '.join(bits)} | {r.get('registrant')}")
        print()
    print("-- " + ", ".join(f"{v} {k.lower()}" for k, v in sorted(verdicts.items())))
    if verdicts.get("NOT REGISTERED"):
        print("\nAn unregistered DOI is strong evidence of invention -- but read the source")
        print("text first. Word autocorrects hyphens inside DOIs into en dashes, and a DOI")
        print("split over a line break loses characters; both look identical to a fake.")
    if verdicts.get("TRUNCATED?"):
        print("\nTRUNCATED? = the suffix is too short to be a real DOI. Nearly always a")
        print("copy-paste or line-wrap slip in the document, NOT a fabricated reference.")
    if verdicts.get("UNCLEAR") or verdicts.get("NETWORK ERROR"):
        print("\nSome lookups did not complete. UNCLEAR and NETWORK ERROR mean 'not checked'")
        print("-- never treat them as evidence that a reference does not exist.")
    print("\nA registered DOI proves the DOI is real, NOT that the citation matches it.")
    print("Compare the metadata above against what each citation claims.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dois", nargs="*", help="DOIs to check")
    ap.add_argument("--file", help="file of DOIs or prose containing them")
    ap.add_argument("--email", help="contact email for Crossref's polite pool")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between requests")
    args = ap.parse_args()

    # Windows consoles default to cp1252 and hard-crash on curly quotes and accented
    # author names, which are ordinary in bibliographic metadata.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    text = " ".join(args.dois)
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            text += "\n" + fh.read()
    if not text.strip() and not sys.stdin.isatty():
        text += "\n" + sys.stdin.read()

    dois = extract_dois(text)
    if not dois:
        sys.exit("No DOIs found. Pass them as arguments, via --file, or on stdin.")

    results = []
    for i, doi in enumerate(dois):
        results.append(check(doi, args.email))
        if i + 1 < len(dois):
            time.sleep(args.delay)

    if args.json:
        json.dump(results, sys.stdout, indent=2)
        print()
    else:
        render(results)

    sys.exit(1 if any(r["status"] == "NOT REGISTERED" for r in results) else 0)


if __name__ == "__main__":
    main()
