import asyncio

import aiohttp

from durbx.cli import build_parser
from durbx.enumerator import enumerate_directories


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_follow_redirects_cli_default_and_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.follow_redirects is False
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt", "--follow-redirects"])
    assert args.follow_redirects is True


def test_redirects_not_followed_by_default() -> None:
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
    for _, _, kwargs in sessions[0].requests:
        assert kwargs.get("allow_redirects") is False


def test_redirects_followed_when_enabled() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            follow_redirects=True,
        )
    )
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 1
    # The soft-404 wildcard probe plus one request per wordlist entry.
    assert len(sessions[0].requests) == 3
    for _, _, kwargs in sessions[0].requests:
        assert kwargs.get("allow_redirects") is True
