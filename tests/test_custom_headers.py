import asyncio

import aiohttp
import pytest

from durbx.cli import build_parser, main
from durbx.enumerator import enumerate_directories, parse_headers


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_parse_headers_basic() -> None:
    assert parse_headers(["Authorization: Bearer abc", "X-Debug: 1"]) == {
        "Authorization": "Bearer abc",
        "X-Debug": "1",
    }


def test_parse_headers_value_may_contain_colons() -> None:
    assert parse_headers(["X-Time: 12:30:00"]) == {"X-Time": "12:30:00"}


def test_parse_headers_strips_whitespace() -> None:
    assert parse_headers(["  X-Foo  :  bar  "]) == {"X-Foo": "bar"}


def test_parse_headers_empty_input() -> None:
    assert parse_headers(None) == {}
    assert parse_headers([]) == {}


def test_parse_headers_last_duplicate_wins() -> None:
    assert parse_headers(["X-A: 1", "X-A: 2"]) == {"X-A": "2"}


def test_parse_headers_rejects_missing_colon() -> None:
    with pytest.raises(ValueError):
        parse_headers(["NoColonHere"])


def test_parse_headers_rejects_empty_name() -> None:
    with pytest.raises(ValueError):
        parse_headers([": value"])


def test_parse_headers_rejects_invalid_name() -> None:
    with pytest.raises(ValueError):
        parse_headers(["Bad Header: x"])
    with pytest.raises(ValueError):
        parse_headers(["X-Foo(bar): x"])


def test_cli_header_flag_default_and_append() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.header is None
    args = parser.parse_args([
        "-u", "example.com", "-w", "custom.txt",
        "-H", "Authorization: Bearer abc",
        "-H", "X-Debug: 1",
    ])
    assert args.header == ["Authorization: Bearer abc", "X-Debug: 1"]


def test_invalid_header_rejected_by_main(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "http://example.com", "-w", str(wordlist), "-H", "NoColon"]) == 2
    assert main(["-u", "http://example.com", "-w", str(wordlist), "-H", "Bad Header: x"]) == 2


def test_custom_headers_sent_with_session() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin"],
            threads=1,
            custom_headers={"Authorization": "Bearer abc", "X-Debug": "1"},
        )
    )
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 1
    assert sessions[0].headers == {
        "User-Agent": "DurbX/0.1",
        "Authorization": "Bearer abc",
        "X-Debug": "1",
    }


def test_custom_header_overrides_user_agent() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin"],
            threads=1,
            user_agent="DurbX/0.1",
            custom_headers={"User-Agent": "EvilScanner/9.9"},
        )
    )
    sessions = aiohttp.ClientSession.instances
    assert sessions[0].headers == {"User-Agent": "EvilScanner/9.9"}
