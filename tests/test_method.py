import asyncio

import pytest

import aiohttp

from durbx.cli import build_parser, main
from durbx.enumerator import DEFAULT_METHOD, enumerate_directories, parse_method


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_parse_method_defaults_and_normalizes() -> None:
    assert parse_method(None) == "GET"
    assert parse_method("") == "GET"
    assert parse_method("get") == "GET"
    assert parse_method("Head") == "HEAD"
    assert parse_method("post") == "POST"


def test_parse_method_rejects_unknown_verbs() -> None:
    for bad in ("PUT", "DELETE", "OPTIONS", "TRACE", "FROBNICATE"):
        with pytest.raises(ValueError, match="Invalid HTTP method"):
            parse_method(bad)


def test_method_cli_default_and_override() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.method == DEFAULT_METHOD == "GET"
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt", "-m", "HEAD"])
    assert args.method == "HEAD"


def test_invalid_method_rejected(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "http://example.com", "-w", str(wordlist), "-m", "PUT"]) == 2


def test_default_get_sent() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin"],
            threads=1,
        )
    )
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 1
    # The soft-404 wildcard probe plus one request per wordlist entry.
    methods = [method for method, _, _ in sessions[0].requests]
    assert methods == ["GET", "GET"]


def test_custom_method_sent() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            method="HEAD",
        )
    )
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 1
    methods = [method for method, _, _ in sessions[0].requests]
    assert methods == ["HEAD", "HEAD", "HEAD"]
