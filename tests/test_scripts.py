"""Offline tests for the two lookup scripts. No network is used: lookups are replaced."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dois = load("check_dois")
books = load("check_books")


def result(status: str, doi: str = "10.1/x") -> dict:
    return {"doi": doi, "status": status, "http": 200}


class TestDoiCoverage:
    def test_clear_answers_are_decided_and_unclear_ones_are_not(self):
        rows = [
            result("REGISTERED"),
            result("NOT REGISTERED"),
            result("TRUNCATED?"),
            result("UNCLEAR"),
            result("NETWORK ERROR"),
            result("NETWORK ERROR"),
        ]
        block = dois.coverage_block(rows)
        assert (block["unit"], block["items"], block["decided"], block["undecided"]) == (
            "DOIs",
            6,
            3,
            3,
        )
        assert block["reasons"] == {"lookup_unclear": 1, "network_error": 2}
        assert block["decided"] + block["undecided"] == block["items"]
        assert sum(block["reasons"].values()) == block["undecided"]

    def test_describe_and_share(self):
        block = dois.coverage_block([result("REGISTERED"), result("NETWORK ERROR")])
        assert dois.describe_coverage(block) == (
            "decided 1 of 2 DOIs; 1 could not be checked (network_error 1)"
        )
        assert dois.decided_share(block) == 50.0
        assert dois.decided_share(dois.coverage_block([])) is None

    def run_main(self, monkeypatch, capsys, rows, *argv):
        monkeypatch.setattr(dois, "check", lambda doi, email: rows[doi])
        monkeypatch.setattr(dois.time, "sleep", lambda _s: None)
        monkeypatch.setattr(sys, "argv", ["check_dois.py", *rows, *argv])
        with pytest.raises(SystemExit) as stop:
            dois.main()
        return stop.value.code, capsys.readouterr()

    ROWS = {"10.1234/a": result("REGISTERED", "10.1234/a"), "10.1234/b": result("NETWORK ERROR", "10.1234/b")}

    def test_json_stays_a_bare_list_unless_coverage_is_asked_for(self, monkeypatch, capsys):
        code, out = self.run_main(monkeypatch, capsys, self.ROWS, "--json")
        assert code == 0
        assert isinstance(json.loads(out.out), list)
        assert "coverage: decided 1 of 2 DOIs" in out.err

    def test_json_with_coverage_wraps_the_results(self, monkeypatch, capsys):
        code, out = self.run_main(monkeypatch, capsys, self.ROWS, "--json", "--with-coverage")
        data = json.loads(out.out)
        assert set(data) == {"coverage", "results"} and len(data["results"]) == 2
        assert data["coverage"]["undecided"] == 1

    def test_text_output_ends_with_the_coverage_line(self, monkeypatch, capsys):
        _, out = self.run_main(monkeypatch, capsys, self.ROWS)
        assert out.out.rstrip().splitlines()[-1].startswith("Coverage: decided 1 of 2 DOIs")

    def test_min_coverage_exit_codes(self, monkeypatch, capsys):
        assert self.run_main(monkeypatch, capsys, self.ROWS, "--min-coverage", "50")[0] == 0
        assert self.run_main(monkeypatch, capsys, self.ROWS, "--min-coverage", "51")[0] == 3
        assert self.run_main(monkeypatch, capsys, self.ROWS)[0] == 0

    def test_an_unregistered_doi_wins_over_low_coverage(self, monkeypatch, capsys):
        rows = {"10.1234/a": result("NOT REGISTERED", "10.1234/a"), "10.1234/b": result("UNCLEAR", "10.1234/b")}
        assert self.run_main(monkeypatch, capsys, rows, "--min-coverage", "100")[0] == 1


def book(status: str, title: str = "A long enough book title") -> dict:
    return {"cited": {"title": title, "year": "2001"}, "res": {"status": status, "match": None, "searched": []}}


class TestBookCoverage:
    def test_found_and_not_in_catalogues_are_decided_failed_lookups_are_not(self):
        rows = [book("FOUND"), book("NOT IN CATALOGUES"), book("LOOKUP FAILED")]
        block = books.coverage_block(rows)
        assert (block["unit"], block["items"], block["decided"], block["undecided"]) == (
            "references",
            3,
            2,
            1,
        )
        assert block["reasons"] == {"lookup_failed": 1}
        assert "prompt to look" in block["notes"][0]

    def test_short_titles_are_undecided_items_not_silently_dropped(self):
        block = books.coverage_block([book("FOUND")], title_too_short=2)
        assert (block["items"], block["decided"], block["undecided"]) == (3, 1, 2)
        assert block["reasons"] == {"title_too_short": 2}

    def test_entries_that_do_not_look_like_books_are_noted_not_counted(self):
        block = books.coverage_block([book("FOUND")], not_book_like=2)
        assert block["items"] == 1
        assert "2 entries did not look like a book and were not checked (use --all)" in block["notes"][1]
        one = books.coverage_block([book("FOUND")], not_book_like=1)
        assert "1 entry did not look like a book and was not checked" in one["notes"][1]

    def test_describe_and_share(self):
        block = books.coverage_block([book("FOUND"), book("LOOKUP FAILED")])
        assert books.describe_coverage(block) == (
            "decided 1 of 2 references; 1 could not be checked (lookup_failed 1)"
        )
        assert books.decided_share(block) == 50.0

    def test_main_json_carries_the_block_and_min_coverage_applies(self, monkeypatch, capsys, tmp_path):
        refs = tmp_path / "refs.txt"
        refs.write_text(
            "Smith, J. (2001). A long enough book title. London: Penguin Books.\n"
            "Doe, A. (1999). Another long enough book title. Oxford: Oxford University Press.\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(books, "self_test", lambda: True)
        monkeypatch.setattr(books, "controls", lambda: {"openlibrary": True})
        outcomes = iter(["FOUND", "LOOKUP FAILED"])
        monkeypatch.setattr(
            books, "check", lambda cited, live: {"status": next(outcomes), "match": None, "searched": []}
        )

        def run(*argv):
            nonlocal outcomes
            outcomes = iter(["FOUND", "LOOKUP FAILED"])
            monkeypatch.setattr(sys, "argv", ["check_books.py", "--file", str(refs), "--all", *argv])
            with pytest.raises(SystemExit) as stop:
                books.main()
            return stop.value.code, capsys.readouterr()

        code, out = run("--json")
        data = json.loads(out.out)
        assert code == 0 and data["coverage"]["undecided"] == 1
        assert {"sources_live", "results", "coverage"} == set(data)
        assert "coverage: decided 1 of 2 references" in out.err
        assert run("--min-coverage", "51")[0] == 3
        assert run("--min-coverage", "50")[0] == 0


def test_every_script_still_starts():
    for name in ("check_dois", "check_books"):
        assert hasattr(load(name), "main")


def test_stdout_is_not_polluted_in_json_mode(monkeypatch, capsys):
    monkeypatch.setattr(dois, "check", lambda doi, email: result("REGISTERED", doi))
    monkeypatch.setattr(sys, "argv", ["check_dois.py", "10.1234/a", "--json"])
    with pytest.raises(SystemExit):
        dois.main()
    json.loads(capsys.readouterr().out)  # raises if anything but JSON was printed to stdout


def test_stringio_is_available():  # keeps the import used for readers extending these tests
    assert io.StringIO("x").read() == "x"
