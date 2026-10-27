import asyncio

import pytest

from durbx.cli import build_parser, main
from durbx.enumerator import (
    RateLimiter,
    enumerate_directories,
    parse_rate_limit,
)


def test_parse_rate_limit() -> None:
    assert parse_rate_limit(None) is None
    assert parse_rate_limit(10) == 10.0
    assert parse_rate_limit(2.5) == 2.5
    with pytest.raises(ValueError):
        parse_rate_limit(0)
    with pytest.raises(ValueError):
        parse_rate_limit(-5)


def test_rate_limit_cli_parsing_and_rejection(tmp_path) -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt"])
    assert args.rate_limit is None
    args = parser.parse_args(
        ["-u", "example.com", "-w", "words.txt", "--rate-limit", "10"]
    )
    assert args.rate_limit == 10.0
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "http://example.com", "-w", str(wordlist), "--rate-limit", "0"]) == 2
    assert main(["-u", "http://example.com", "-w", str(wordlist), "--rate-limit", "-3"]) == 2


def _frozen_clock_and_sleep():
    now = [1000.0]
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    return now, sleeps, fake_sleep


def test_token_bucket_burst_then_wait() -> None:
    now, sleeps, fake_sleep = _frozen_clock_and_sleep()
    limiter = RateLimiter(2, clock=lambda: now[0], sleep=fake_sleep)
    # Capacity is one second's worth (2 tokens): the first two requests
    # go out immediately, the third must wait for one token (0.5s).
    asyncio.run(limiter.acquire())
    asyncio.run(limiter.acquire())
    assert sleeps == []
    asyncio.run(limiter.acquire())
    assert sleeps == [pytest.approx(0.5)]


def test_token_bucket_refills_over_time() -> None:
    now, sleeps, fake_sleep = _frozen_clock_and_sleep()
    limiter = RateLimiter(2, clock=lambda: now[0], sleep=fake_sleep)
    asyncio.run(limiter.acquire())
    asyncio.run(limiter.acquire())
    # One second later the bucket is full again: no wait needed.
    now[0] += 1.0
    asyncio.run(limiter.acquire())
    assert sleeps == []


def test_rate_limit_throttles_scan_requests(monkeypatch) -> None:
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["a", "b", "c"],
            threads=1,
            rate_limit=2,
            detect_wildcards=False,
        )
    )
    assert summary.total == 3
    assert summary.completed == 3
    assert summary.hits == 3
    # Burst of 2, then one throttled request (real-clock drift allowed).
    assert sleeps == [pytest.approx(0.5, abs=0.01)]
