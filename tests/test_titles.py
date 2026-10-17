"""Offline tests for check_titles.py. No network is used: the index searches are replaced."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
spec = importlib.util.spec_from_file_location("check_titles", SCRIPTS / "check_titles.py")
ct = importlib.util.module_from_spec(spec)
sys.modules["check_titles"] = ct
spec.loader.exec_module(ct)

HARDIN = "Hardin, G. (1968). The Tragedy of the Commons. Science, 162(3859), 1243-1248."


def record(title="The Tragedy of the Commons", families=("Hardin",), years=(1968,),
           container="Science", type_="journal-article", source="Crossref"):
    return {"source": source, "title": title, "families": list(families), "years": list(years),
            "container": container, "type": type_, "doi": "10.1126/science.162.3859.1243"}


def searching(*records, name="fake_search"):
    def search(title, surname):
        return None if records == (None,) else list(records)
    search.__name__ = name
    return search


class TestParse:
    def test_article(self):
        e = ct.parse_entry(HARDIN)
        assert (e["surname"], e["year"], e["title"]) == ("Hardin", 1968, "The Tragedy of the Commons")
        assert e["rest"].startswith("Science, 162(3859)")
        assert not e["has_doi"]

    def test_several_authors_and_a_subtitle(self):
        line = ("Ashworth, K. N., Mwangi, T. F., & Iyer, E. H. (2017). Negotiating kinship: life "
                "satisfaction among market women. Administrative Science Quarterly, 34(6), 1-9.")
        e = ct.parse_entry(line)
        assert e["surname"] == "Ashworth"
        assert e["title"] == "Negotiating kinship: life satisfaction among market women"

    def test_organisation_has_no_surname(self):
        e = ct.parse_entry("Institute for Development Studies (2012). School feeding: Evaluation "
                           "report. Institute for Development Studies, Nairobi.")
        assert e["surname"] is None and e["year"] == 2012
        assert e["title"] == "School feeding: Evaluation report"

    def test_an_initial_inside_the_title_does_not_end_it(self):
        e = ct.parse_entry("Smith, J. (2010). Trade between the U.S. and Africa since independence. "
                           "Oxford University Press.")
        assert e["title"] == "Trade between the U.S. and Africa since independence"

    def test_no_date_and_a_doi(self):
        e = ct.parse_entry("Lee, A. (n.d.). A study of things and other matters. https://doi.org/10.1234/abc")
        assert e["year"] is None and e["has_doi"]

    def test_an_unparsable_line_has_no_title(self):
        assert ct.parse_entry("just some words without a year in them at all really")["title"] is None


class TestMatching:
    def test_same_title_in_any_case_or_punctuation(self):
        assert ct.title_score("The Tragedy of the Commons", "the tragedy of the commons.") == 1.0

    def test_a_subtitle_on_one_side_still_matches(self):
        assert ct.title_score("The ecology of human development",
                              "The ecology of human development: experiments by nature and design") >= 0.9
        assert ct.title_score("Soil carbon: a review", "Soil carbon: new estimates") < 0.85

    def test_short_generic_titles_need_to_be_equal(self):
        assert ct.title_score("Climate change", "Climate change and health in Africa") < 0.85

    def test_different_titles_do_not_match(self):
        assert ct.title_score("Soil carbon in tropical forests", "Atrial fibrillation and stroke risk") < 0.5

    @pytest.mark.parametrize(("cited", "rec", "same"), [
        ("Science", "Science", True),
        ("Proc Natl Acad Sci U S A", "Proceedings of the National Academy of Sciences", True),
        ("J. Appl. Psychol.", "Journal of Applied Psychology", True),
        ("Science", "Nature Medicine", False),
        ("Administrative Science Quarterly", "American Journal of Sociology", False),
    ])
    def test_same_journal(self, cited, rec, same):
        assert ct.same_journal(cited, rec) is same


class TestCompare:
    cited = ct.parse_entry(HARDIN)

    def test_everything_agrees(self):
        assert ct.compare(self.cited, record()) == ([], [])

    def test_first_author_differs(self):
        assert ct.compare(self.cited, record(families=("Ostrom", "Hardin"))) == (["first author"], [])

    def test_year_may_be_any_of_the_record_years(self):
        assert ct.compare(self.cited, record(years=(1967, 1968))) == ([], [])
        assert ct.compare(self.cited, record(years=(1970,))) == (["year"], [])

    def test_the_year_of_a_book_is_for_review_not_a_difference(self):
        book = ct.parse_entry("Kuhn, T. S. (1962). The structure of scientific revolutions. University of Chicago Press.")
        rec = record(title="The structure of scientific revolutions", families=("Kuhn",), years=(1996,),
                     container="", type_="book")
        assert ct.compare(book, rec) == ([], ["year"])

    def test_journal_is_compared_only_for_journal_articles_cited_as_such(self):
        assert ct.compare(self.cited, record(container="Nature")) == (["journal"], [])
        assert ct.compare(self.cited, record(container="Nature", type_="report")) == ([], [])
        assert ct.compare(self.cited, record(container="Nature", type_="article")) == (["journal"], [])

    def test_the_institution_of_a_thesis_is_compared(self):
        thesis = ct.parse_entry("Oriwo, E. A. (2012). A long thesis title about markets. University of Nairobi.")
        ok = record(title="x", families=("Oriwo",), years=(2012,), container="University of Nairobi Research Archive",
                    type_="dissertation")
        bad = {**ok, "container": "University of Ghana Repository"}
        assert ct.compare(thesis, ok) == ([], [])
        assert ct.compare(thesis, bad) == (["institution"], [])

    def test_a_record_without_authors_or_years_is_not_held_against_the_citation(self):
        assert ct.compare(self.cited, record(families=(), years=())) == ([], [])

    def test_an_organisation_citation_skips_the_author_check(self):
        org = ct.parse_entry("World Health Organization (2019). Global report on health systems. WHO.")
        assert ct.compare(org, record(families=("Smith",), years=(2019,), type_="report")) == ([], [])


class TestCompatibility:
    book = ct.parse_entry("Ake, C. (1996). Democracy and development in Africa. Brookings Institution.")

    @pytest.mark.parametrize("kind", ["book-chapter", "journal-article", "article", "proceedings-article",
                                      "reference-entry", "posted-content"])
    def test_a_book_citation_is_not_matched_to_an_article_or_chapter(self, kind):
        assert not ct.compatible(self.book, record(type_=kind))

    @pytest.mark.parametrize("kind", ["book", "monograph", "report", "dissertation", "edited-book"])
    def test_a_book_citation_can_match_a_book_report_or_thesis(self, kind):
        assert ct.compatible(self.book, record(type_=kind))

    def test_a_journal_citation_can_match_anything(self):
        assert ct.compatible(ct.parse_entry(HARDIN), record(type_="book-chapter"))

    def test_an_extra_word_makes_a_different_title(self):
        assert ct.title_score("Thinking, fast and slow", "Thinking Fast and Slow in AI") < 0.85
        assert ct.title_score("Thinking, fast and slow", "Thinking Fast and Slow") >= 0.99


class TestCheck:
    def test_found(self):
        r = ct.check(ct.parse_entry(HARDIN), [searching(record())])
        assert r["status"] == "FOUND" and r["differences"] == []
        assert r["match"]["source"] == "Crossref"

    def test_found_but_the_citation_has_the_wrong_authors(self):
        cited = ct.parse_entry(HARDIN.replace("Hardin, G.", "Al-Hajj, M."))
        r = ct.check(cited, [searching(record())])
        assert r["status"] == "FOUND_DIFFERS" and r["differences"] == ["first author"]

    def test_the_better_agreeing_candidate_wins(self):
        wrong = record(families=("Other",), years=(1968,))
        right = record()
        r = ct.check(ct.parse_entry(HARDIN), [searching(wrong, right)])
        assert r["status"] == "FOUND"

    def test_falls_through_to_the_next_index(self):
        r = ct.check(ct.parse_entry(HARDIN),
                     [searching(record(title="Something else entirely")), searching(record(source="OpenAlex"))])
        assert r["status"] == "FOUND" and r["match"]["source"] == "OpenAlex"

    def test_a_book_whose_year_differs_is_left_for_review(self):
        cited = ct.parse_entry("Kuhn, T. S. (1962). The structure of scientific revolutions. University of Chicago Press.")
        rec = record(title="The structure of scientific revolutions", families=("Kuhn",), years=(1996,),
                     container="", type_="book")
        r = ct.check(cited, [searching(rec)])
        assert r["status"] == "FOUND_REVIEW" and r["review"] == ["year"] and r["differences"] == []

    def test_two_works_with_the_title_and_neither_by_the_cited_author_is_ambiguous(self):
        cited = ct.parse_entry("Cormen, T. H. (2009). Introduction to algorithms. MIT Press.")
        a = record(title="Introduction to algorithms", families=("Grossman",), years=(2009,), type_="book", container="")
        b = record(title="Introduction to algorithms", families=("Rayward-Smith",), years=(1991,), type_="book", container="")
        assert ct.check(cited, [searching(a, b)])["status"] == "AMBIGUOUS"

    def test_a_single_other_author_for_the_same_title_is_a_difference(self):
        cited = ct.parse_entry("Cormen, T. H. (2009). Introduction to algorithms. MIT Press.")
        a = record(title="Introduction to algorithms", families=("Grossman",), years=(2009,), type_="book", container="")
        assert ct.check(cited, [searching(a)])["status"] == "FOUND_DIFFERS"

    def test_candidates_from_every_index_are_pooled(self):
        wrong = record(families=("Other",))
        r = ct.check(ct.parse_entry(HARDIN), [searching(wrong), searching(record(source="OpenAlex"))])
        assert r["status"] == "FOUND" and r["match"]["source"] == "OpenAlex"

    def test_no_close_title_is_not_found_and_says_nothing_about_fabrication(self):
        r = ct.check(ct.parse_entry(HARDIN), [searching(record(title="A different paper on grazing"))])
        assert r["status"] == "NOT FOUND"

    def test_every_index_failing_is_a_network_error_not_an_absence(self):
        r = ct.check(ct.parse_entry(HARDIN), [searching(None), searching(None)])
        assert r["status"] == "NETWORK ERROR"

    def test_one_index_answering_is_enough_to_say_not_found(self):
        r = ct.check(ct.parse_entry(HARDIN), [searching(None, name="down"), searching(record(title="Unrelated work here"))])
        assert r["status"] == "NOT FOUND" and r["sources_failed"] == ["down"]

    def test_no_usable_title(self):
        r = ct.check(ct.parse_entry("just some words without a year in them at all really"), [searching(record())])
        assert r["status"] == "NOT CHECKED"


class TestCoverage:
    ROWS = [{"status": s} for s in ("FOUND", "FOUND_DIFFERS", "NOT FOUND", "NOT FOUND", "NETWORK ERROR", "NOT CHECKED")]

    def test_block(self):
        block = ct.coverage_block(self.ROWS)
        assert (block["unit"], block["items"], block["decided"], block["undecided"]) == ("references", 6, 2, 4)
        assert block["reasons"] == {"network_error": 1, "no_usable_title": 1, "not_in_index": 2}
        assert block["decided"] + block["undecided"] == block["items"]
        assert sum(block["reasons"].values()) == block["undecided"]

    def test_describe_and_share(self):
        block = ct.coverage_block(self.ROWS)
        assert ct.describe_coverage(block).startswith("decided 2 of 6 references; 4 could not be checked (not_in_index 2")
        assert ct.decided_share(block) == 33.3
        assert ct.decided_share(ct.coverage_block([])) is None


class TestMain:
    LINES = [HARDIN, "Lee, A. (2001). A study of things and other matters. Journal of Stuff, 4, 1-2. https://doi.org/10.1234/abc"]

    def run(self, monkeypatch, capsys, *argv, searches=None):
        searches = searches or [searching(record())]
        searches[0].__name__ = "fake_search"
        monkeypatch.setattr(ct, "SOURCES", searches)
        monkeypatch.setattr(ct.time, "sleep", lambda _s: None)
        monkeypatch.setattr(ct, "controls", lambda *_a: {"fake_search": True})
        monkeypatch.setattr(sys, "argv", ["check_titles.py", *argv])
        with pytest.raises(SystemExit) as stop:
            ct.main()
        return stop.value.code, capsys.readouterr()

    def test_entries_with_a_doi_are_skipped_unless_all_is_given(self, monkeypatch, capsys):
        code, out = self.run(monkeypatch, capsys, *self.LINES, "--json")
        assert code == 0 and len(json.loads(out.out)["results"]) == 1
        _code, out = self.run(monkeypatch, capsys, *self.LINES, "--json", "--all")
        assert len(json.loads(out.out)["results"]) == 2

    def test_json_carries_the_coverage_block(self, monkeypatch, capsys):
        _code, out = self.run(monkeypatch, capsys, HARDIN, "--json")
        data = json.loads(out.out)
        assert data["coverage"]["decided"] == 1 and "coverage: decided 1 of 1 references" in out.err

    def test_min_coverage_exits_3_when_nothing_was_found(self, monkeypatch, capsys):
        none_found = [searching(record(title="A different paper on grazing"))]
        code, out = self.run(monkeypatch, capsys, HARDIN, "--min-coverage", "50", searches=none_found)
        assert code == 3 and "below --min-coverage" in out.err

    def test_a_failed_control_aborts_instead_of_reporting_absences(self, monkeypatch, capsys):
        monkeypatch.setattr(ct, "controls", lambda *_a: {"fake_search": False})
        monkeypatch.setattr(sys, "argv", ["check_titles.py", HARDIN])
        with pytest.raises(SystemExit) as stop:
            ct.main()
        assert "control" in str(stop.value)

    def test_human_output_says_not_found_is_not_a_verdict(self, monkeypatch, capsys):
        none_found = [searching(record(title="A different paper on grazing"))]
        _code, out = self.run(monkeypatch, capsys, HARDIN, searches=none_found)
        assert "NOT FOUND" in out.out and "not a verdict" in out.out


class TestFetch:
    def test_a_spent_daily_budget_fails_fast_instead_of_waiting(self, monkeypatch):
        import io
        import urllib.error

        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "50014"}, io.BytesIO(b"{}"))

        slept = []
        monkeypatch.setattr(ct.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(ct.time, "sleep", slept.append)
        assert ct.fetch("https://api.openalex.org/works?search=x") == (None, False)
        assert len(calls) == 1 and slept == []

    def test_a_short_retry_after_is_waited_for(self, monkeypatch):
        import io
        import urllib.error

        responses = []

        class Ok:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(req, timeout=0):
            if not responses:
                responses.append(1)
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "3"}, io.BytesIO(b"{}"))
            return Ok()

        slept = []
        monkeypatch.setattr(ct.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(ct.time, "sleep", slept.append)
        assert ct.fetch("https://api.crossref.org/works") == ({"ok": True}, True)
        assert slept == [3.0]


def test_a_review_result_is_undecided_in_the_coverage_block():
    block = ct.coverage_block([{"status": "FOUND"}, {"status": "FOUND_REVIEW"}, {"status": "AMBIGUOUS"}])
    assert block["decided"] == 1
    assert block["reasons"] == {"ambiguous_title": 1, "year_may_be_an_edition": 1}
