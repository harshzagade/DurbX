import asyncio

import aiohttp

from durbx import enumerator as enumerator_mod
from durbx.cli import build_parser, main
from durbx.enumerator import DEFAULT_USER_AGENT, enumerate_directories


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_user_agent_cli_default_and_override() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.user_agent == DEFAULT_USER_AGENT == "DurbX/0.1"
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt", "--user-agent", "CustomScanner/2.0"])
    assert args.user_agent == "CustomScanner/2.0"


def test_empty_user_agent_rejected(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "http://example.com", "-w", str(wordlist), "--user-agent", ""]) == 2
    assert main(["-u", "http://example.com", "-w", str(wordlist), "--user-agent", "   "]) == 2


def test_default_user_agent_sent() -> None:
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
    assert sessions[0].headers == {"User-Agent": "DurbX/0.1"}


def test_custom_user_agent_sent() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            user_agent="CustomScanner/2.0",
        )
    )
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 1
    assert sessions[0].headers == {"User-Agent": "CustomScanner/2.0"}
    # 3 GETs: the soft-404 wildcard probe plus one per wordlist entry.
    assert sessions[0].get_count == 3
