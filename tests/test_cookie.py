import aiohttp
import pytest

from durbx.cli import build_parser, main
from durbx.enumerator import build_cookie_header, parse_cookies


def test_parse_cookies_single() -> None:
    assert parse_cookies(["session=abc123"]) == {"session": "abc123"}


def test_parse_cookies_multiple_and_value_with_equals() -> None:
    # A base64-padded value keeps its trailing '=' (split on the first).
    parsed = parse_cookies(["session=abc123", "token=xyz==", "theme=dark"])
    assert parsed == {"session": "abc123", "token": "xyz==", "theme": "dark"}


def test_parse_cookies_empty_value_allowed() -> None:
    assert parse_cookies(["session="]) == {"session": ""}


def test_parse_cookies_later_duplicate_wins() -> None:
    assert parse_cookies(["a=1", "a=2"]) == {"a": "2"}


def test_parse_cookies_empty_input() -> None:
    assert parse_cookies(None) == {}
    assert parse_cookies([]) == {}


def test_parse_cookies_rejects_malformed() -> None:
    bad = [
        "session",  # no '='
        "=abc",  # empty name
        "a b=1",  # space in name
        "a;b=1",  # ';' in name (not a token char)
        "a=1;2",  # ';' in value would split the header
        "a=1,2",  # ',' in value
        'a=1"2',  # '"' in value
        "a=1 2",  # space in value
        "a=1\t2",  # tab in value
    ]
    for item in bad:
        with pytest.raises(ValueError):
            parse_cookies([item])


def test_build_cookie_header_combines_pairs() -> None:
    assert build_cookie_header({"session": "abc123", "theme": "dark"}) == (
        "session=abc123; theme=dark"
    )


def test_build_cookie_header_empty_is_none() -> None:
    assert build_cookie_header(None) is None
    assert build_cookie_header({}) is None


def test_cli_accepts_repeatable_cookie_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["-u", "example.com", "-w", "words.txt",
         "--cookie", "session=abc123", "--cookie", "theme=dark"]
    )
    assert args.cookie == ["session=abc123", "theme=dark"]


def test_cli_cookie_flag_defaults_none() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt"])
    assert args.cookie is None


def _run_main(tmp_path, *extra_args) -> int:
    """Run the CLI against the stub session (answers 200 to everything)
    and return the exit code."""
    aiohttp.ClientSession.instances.clear()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    return main(
        ["-u", "example.com", "-w", str(wordlist), "--no-wildcard", "-q", *extra_args]
    )


def test_main_cookie_reaches_session_headers(tmp_path) -> None:
    assert _run_main(tmp_path, "--cookie", "session=abc123", "--cookie", "theme=dark") == 0
    session = aiohttp.ClientSession.instances[-1]
    assert session.headers["Cookie"] == "session=abc123; theme=dark"
    assert session.headers["User-Agent"] == "DurbX/0.1"


def test_main_explicit_header_cookie_wins(tmp_path) -> None:
    assert (
        _run_main(
            tmp_path,
            "--cookie",
            "session=from-flag",
            "-H",
            "Cookie: session=from-header",
        )
        == 0
    )
    session = aiohttp.ClientSession.instances[-1]
    assert session.headers["Cookie"] == "session=from-header"


def test_main_bad_cookie_exits_2(tmp_path) -> None:
    assert _run_main(tmp_path, "--cookie", "not-a-pair") == 2
    assert _run_main(tmp_path, "--cookie", "a=1;2") == 2
