import asyncio

import aiohttp
import pytest

from durbx import enumerator as enumerator_mod
from durbx.cli import build_parser, main
from durbx.enumerator import DEFAULT_DELAY, enumerate_directories


def _patch_sleep(monkeypatch) -> list:
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_delay_cli_default_and_override() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.delay == DEFAULT_DELAY == 0.0
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt", "--delay", "0.5"])
    assert args.delay == 0.5


def test_negative_delay_rejected(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "http://example.com", "-w", str(wordlist), "--delay", "-1"]) == 2


def test_per_worker_delay_between_requests(monkeypatch) -> None:
    _reset_stub_sessions()
    sleeps = _patch_sleep(monkeypatch)
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["a", "b", "c"],
            threads=1,
            delay=0.25,
        )
    )
    assert summary.total == 3
    assert summary.completed == 3
    assert sleeps == [0.25, 0.25, 0.25]


def test_zero_delay_means_no_sleep(monkeypatch) -> None:
    _reset_stub_sessions()
    sleeps = _patch_sleep(monkeypatch)
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["a", "b"],
            threads=1,
            delay=0.0,
        )
    )
    assert sleeps == []
