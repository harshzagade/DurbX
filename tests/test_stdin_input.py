import io
import sys

import aiohttp
import pytest

from durbx.cli import build_parser, main
from durbx.enumerator import load_stdin_entries, load_wordlist, parse_wordlist_lines


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_parse_wordlist_lines_normalizes() -> None:
    lines = ["admin", "/login", "  backup  ", "", "# comment", "admin", "#x", "/"]
    assert parse_wordlist_lines(lines) == ["admin", "login", "backup"]


def test_load_stdin_entries(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("admin\n/login\n# skip\n\nadmin\n"))
    assert load_stdin_entries() == ["admin", "login"]


def test_load_wordlist_dash_reads_stdin(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("admin\nlogin\n"))
    assert load_wordlist("-") == ["admin", "login"]


def test_stdin_flag_drives_scan(monkeypatch) -> None:
    _reset_stub_sessions()
    monkeypatch.setattr(sys, "stdin", io.StringIO("admin\nlogin\n"))
    rc = main(["-u", "http://example.com", "--stdin", "--no-wildcard", "-q"])
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    requested = [url for _method, url, _kwargs in session.requests]
    assert any(url.endswith("/admin") for url in requested)
    assert any(url.endswith("/login") for url in requested)


def test_dash_wordlist_drives_scan(monkeypatch) -> None:
    _reset_stub_sessions()
    monkeypatch.setattr(sys, "stdin", io.StringIO("admin\n"))
    rc = main(["-u", "http://example.com", "-w", "-", "--no-wildcard", "-q"])
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    assert any(url.endswith("/admin") for _method, url, _kwargs in session.requests)


def test_stdin_and_wordlist_conflict(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("admin\n"))
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(["-u", "http://example.com", "--stdin", "-w", str(wordlist), "-q"])
    assert rc == 2


def test_no_wordlist_and_no_stdin_rejected() -> None:
    assert main(["-u", "http://example.com", "-q"]) == 2


def test_empty_stdin_rejected(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("# only a comment\n"))
    assert main(["-u", "http://example.com", "--stdin", "-q"]) == 2


def test_stdin_cli_flag_parsing() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "--stdin"])
    assert args.stdin is True
    assert args.wordlist is None
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.stdin is False
    assert args.wordlist == "w.txt"
