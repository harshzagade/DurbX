import aiohttp
import pytest

from durbx.cli import main
from durbx.enumerator import filter_excluded_paths, parse_exclude_paths


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_parse_exclude_paths_empty_inputs() -> None:
    assert parse_exclude_paths(None) == []
    assert parse_exclude_paths([]) == []


def test_parse_exclude_paths_compiles_multiple() -> None:
    patterns = parse_exclude_paths([r"^assets/", r"\.bak$"])
    assert len(patterns) == 2
    assert patterns[0].search("assets/logo.png")
    assert not patterns[0].search("admin")
    assert patterns[1].search("config.bak")
    assert not patterns[1].search("config.php")


def test_parse_exclude_paths_bad_regex_fails_fast() -> None:
    with pytest.raises(ValueError, match="Invalid --exclude-path regex"):
        parse_exclude_paths(["[unclosed"])


def test_parse_exclude_paths_empty_pattern_fails_fast() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_exclude_paths(["   "])


def test_filter_excluded_paths_drops_matches_keeps_order() -> None:
    kept, skipped = filter_excluded_paths(
        ["admin", "assets/logo.png", "login", "assets/style.css", "api"],
        parse_exclude_paths([r"^assets/"]),
    )
    assert kept == ["admin", "login", "api"]
    assert skipped == 2


def test_filter_excluded_paths_no_patterns_is_identity() -> None:
    entries = ["admin", "login"]
    kept, skipped = filter_excluded_paths(entries, [])
    assert kept == entries
    assert skipped == 0


def test_cli_exclude_path_skips_matching_entries(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\nassets/logo.png\nlogin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--exclude-path",
            r"^assets/",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    requested = {url for _, url, _ in session.requests}
    assert requested == {
        "https://example.com/admin",
        "https://example.com/login",
    }


def test_cli_exclude_path_repeatable(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\nassets/logo.png\nbackup.bak\nlogin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--exclude-path",
            r"^assets/",
            "--exclude-path",
            r"\.bak$",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    session = aiohttp.ClientSession.instances[-1]
    requested = {url for _, url, _ in session.requests}
    assert requested == {
        "https://example.com/admin",
        "https://example.com/login",
    }


def test_cli_exclude_path_bad_regex_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--exclude-path",
            "[unclosed",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2


def test_cli_exclude_path_excludes_everything_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\nlogin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--exclude-path",
            ".*",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2
