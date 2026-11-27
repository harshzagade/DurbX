import aiohttp

from durbx.cli import main
from durbx.enumerator import filter_included_paths, parse_include_paths

import pytest


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_parse_include_paths_empty_inputs() -> None:
    assert parse_include_paths(None) == []
    assert parse_include_paths([]) == []


def test_parse_include_paths_compiles_multiple() -> None:
    patterns = parse_include_paths([r"^api/", r"\.php$"])
    assert len(patterns) == 2
    assert patterns[0].search("api/users")
    assert not patterns[0].search("admin")
    assert patterns[1].search("login.php")
    assert not patterns[1].search("login")


def test_parse_include_paths_bad_regex_fails_fast() -> None:
    with pytest.raises(ValueError, match="Invalid --include-path regex"):
        parse_include_paths(["[unclosed"])


def test_parse_include_paths_empty_pattern_fails_fast() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_include_paths(["   "])


def test_filter_included_paths_keeps_matches_only() -> None:
    kept, skipped = filter_included_paths(
        ["admin", "api/users", "login", "api/status", "assets/logo.png"],
        parse_include_paths([r"^api/"]),
    )
    assert kept == ["api/users", "api/status"]
    assert skipped == 3


def test_filter_included_paths_no_patterns_is_identity() -> None:
    entries = ["admin", "login"]
    kept, skipped = filter_included_paths(entries, [])
    assert kept == entries
    assert skipped == 0


def test_cli_include_path_scans_matching_entries_only(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\napi/users\nlogin\napi/status\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--include-path",
            r"^api/",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    requested = {url for _, url, _ in session.requests}
    assert requested == {
        "https://example.com/api/users",
        "https://example.com/api/status",
    }


def test_cli_include_path_repeatable(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\napi/users\nlogin.php\nassets/logo.png\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--include-path",
            r"^api/",
            "--include-path",
            r"\.php$",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    requested = {url for _, url, _ in session.requests}
    assert requested == {
        "https://example.com/api/users",
        "https://example.com/login.php",
    }


def test_cli_include_path_bad_regex_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--include-path",
            "[unclosed",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2


def test_cli_include_path_matches_nothing_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\nlogin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--include-path",
            r"^api/",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2


def test_cli_include_then_exclude_carves_holes(tmp_path) -> None:
    # Included AND NOT excluded: ^api/ keeps the subtree, then
    # ^api/internal/ carves its hole out of it.
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("api/users\napi/internal/debug\napi/status\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--include-path",
            r"^api/",
            "--exclude-path",
            r"^api/internal/",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    requested = {url for _, url, _ in session.requests}
    assert requested == {
        "https://example.com/api/users",
        "https://example.com/api/status",
    }
