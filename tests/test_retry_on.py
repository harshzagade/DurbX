import asyncio

import pytest

from durbx import enumerator as enumerator_mod
from durbx.cli import build_parser
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    enumerate_directories,
    fetch_with_retry,
    parse_status_codes,
)
from durbx.formatter import format_result


class _FakeResponse:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(self, status: int, reason: str = "OK", headers: dict | None = None) -> None:
        self.status = status
        self.reason = reason
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    """Replays a script of responses; mimics aiohttp's `session.request(...)` API."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0

    def request(self, method: str, url: str, **kwargs):
        index = min(self.calls, len(self._script) - 1)
        self.calls += 1
        return self._script[index]


def _patch_sleep(monkeypatch) -> list:
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


def test_fetch_retries_503_then_succeeds(monkeypatch) -> None:
    _patch_sleep(monkeypatch)
    session = _FakeSession([_FakeResponse(503), _FakeResponse(200)])
    outcome = asyncio.run(
        fetch_with_retry(session, "https://example.com/x", max_retries=3, retry_on=(503,))
    )
    assert outcome.status == 200
    assert outcome.attempts == 2
    assert session.calls == 2


def test_fetch_does_not_retry_503_by_default(monkeypatch) -> None:
    _patch_sleep(monkeypatch)
    session = _FakeSession([_FakeResponse(503), _FakeResponse(200)])
    outcome = asyncio.run(
        fetch_with_retry(session, "https://example.com/x", max_retries=3)
    )
    assert outcome.status == 503
    assert outcome.attempts == 1
    assert session.calls == 1


def test_fetch_retries_each_listed_code(monkeypatch) -> None:
    _patch_sleep(monkeypatch)
    session = _FakeSession(
        [_FakeResponse(500), _FakeResponse(502), _FakeResponse(200)]
    )
    outcome = asyncio.run(
        fetch_with_retry(
            session, "https://example.com/x", max_retries=3, retry_on=(500, 502, 503)
        )
    )
    assert outcome.status == 200
    assert outcome.attempts == 3


def test_fetch_gives_up_after_max_retries_on_listed_code(monkeypatch) -> None:
    _patch_sleep(monkeypatch)
    session = _FakeSession([_FakeResponse(503)])
    outcome = asyncio.run(
        fetch_with_retry(session, "https://example.com/x", max_retries=2, retry_on=(503,))
    )
    assert outcome.status == 503
    assert outcome.attempts == 3
    assert session.calls == 3


def test_fetch_honors_retry_after_for_listed_code(monkeypatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    session = _FakeSession(
        [_FakeResponse(503, headers={"Retry-After": "7"}), _FakeResponse(200)]
    )
    outcome = asyncio.run(
        fetch_with_retry(session, "https://example.com/x", max_retries=3, retry_on=(503,))
    )
    assert outcome.status == 200
    assert sleeps == [7.0]


def test_fetch_does_not_retry_unlisted_code(monkeypatch) -> None:
    _patch_sleep(monkeypatch)
    session = _FakeSession([_FakeResponse(500), _FakeResponse(200)])
    outcome = asyncio.run(
        fetch_with_retry(session, "https://example.com/x", max_retries=3, retry_on=(503,))
    )
    assert outcome.status == 500
    assert outcome.attempts == 1


def test_retry_on_parses_ranges_like_status_codes() -> None:
    assert parse_status_codes("500,502-503") == [500, 502, 503]
    with pytest.raises(ValueError):
        parse_status_codes("abc")
    with pytest.raises(ValueError):
        parse_status_codes("599-500")


def test_cli_accepts_retry_on_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt", "--retry-on", "500,502,503"])
    assert args.retry_on == "500,502,503"
    assert tuple(parse_status_codes(args.retry_on)) == (500, 502, 503)


def test_scan_threads_retry_on_into_fetch(monkeypatch) -> None:
    """enumerate_directories passes retry_on to fetch_with_retry, so a 503
    that then succeeds reaches on_result as a hit with attempts=2."""
    captured: list[ScanResult] = []
    seen: dict = {}

    async def fake_fetch(session, url, **kwargs):
        seen.update(kwargs)
        return FetchOutcome(status=200, reason="OK", content_length=42, attempts=2)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    asyncio.run(
        enumerate_directories(
            base_url="https://example.com",
            entries=["admin"],
            threads=1,
            detect_wildcards=False,
            on_result=captured.append,
            retry_on=(500, 502, 503),
        )
    )
    assert seen.get("retry_on") == (500, 502, 503)
    assert len(captured) == 1
    assert captured[0].attempts == 2
    assert "(retried 1)" in format_result(captured[0])


def test_scan_defaults_retry_on_to_429(monkeypatch) -> None:
    """Without retry_on, enumerate_directories still retries 429 only."""
    seen: dict = {}

    async def fake_fetch(session, url, **kwargs):
        seen.update(kwargs)
        return FetchOutcome(status=200, reason="OK", content_length=42, attempts=1)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    asyncio.run(
        enumerate_directories(
            base_url="https://example.com",
            entries=["admin"],
            threads=1,
            detect_wildcards=False,
        )
    )
    assert seen.get("retry_on") == (429,)
