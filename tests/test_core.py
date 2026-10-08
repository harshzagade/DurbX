import asyncio

import aiohttp
import pytest

from durbx import enumerator as enumerator_mod
from durbx.enumerator import (
    ScanResult,
    ScanSummary,
    fetch_with_retry,
    load_wordlist,
    normalize_target,
    parse_retry_after,
    parse_status_codes,
    retry_delay,
)
from durbx.formatter import format_result, render_results
from durbx.cli import build_parser


def test_normalize_target_adds_https_scheme() -> None:
    assert normalize_target("example.com") == "https://example.com"


def test_load_wordlist_deduplicates_entries(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\nadmin\n# skip\nlogin\n", encoding="utf-8")
    assert load_wordlist(str(wordlist)) == ["admin", "login"]


def test_render_results_filters_404_by_default() -> None:
    rendered = render_results(
        [
            ScanResult(path="/admin", status_code=200, url="https://example.com/admin", reason="OK", size=12),
            ScanResult(path="/missing", status_code=404, url="https://example.com/missing", reason="Not Found", size=0),
            ScanResult(path="/forbidden", status_code=403, url="https://example.com/forbidden", reason="Forbidden", size=0),
        ]
    )
    assert "/admin" in rendered
    assert "/missing" not in rendered
    assert "/forbidden" not in rendered


def test_cli_uses_url_and_wordlist_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.url == "example.com"
    assert args.wordlist == "custom.txt"


def test_parse_status_codes_parses_comma_list() -> None:
    assert parse_status_codes("200, 403") == [200, 403]


def test_format_result_shows_url_for_accessible_codes() -> None:
    rendered = format_result(ScanResult(path="/admin", status_code=200, url="https://example.com/admin", reason="OK", size=99))
    assert "-> https://example.com/admin" in rendered


def test_format_result_keeps_size_text() -> None:
    rendered = format_result(ScanResult(path="/admin", status_code=403, url="https://example.com/admin", reason="Forbidden", size=42))
    assert "42B" in rendered


def test_scan_summary_dataclass() -> None:
    summary = ScanSummary(total=10, completed=10, hits=2)
    assert summary.hits == 2


class _FakeResponse:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(self, status: int, reason: str = "OK", headers: dict | None = None, error: BaseException | None = None) -> None:
        self.status = status
        self.reason = reason
        self.headers = headers or {}
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    """Replays a script of responses; mimics aiohttp's `session.get(...)` API."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0

    def get(self, url: str, **kwargs):
        index = min(self.calls, len(self._script) - 1)
        self.calls += 1
        return self._script[index]


def _patch_sleep(monkeypatch) -> list:
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


def test_parse_retry_after_numeric_and_clamped() -> None:
    assert parse_retry_after("5") == 5.0
    assert parse_retry_after("2.5") == 2.5
    assert parse_retry_after("120") == enumerator_mod.MAX_RETRY_AFTER_SECONDS


def test_parse_retry_after_invalid_or_missing() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("   ") is None
    assert parse_retry_after("soon") is None
    assert parse_retry_after("-3") is None
    # HTTP-date form is intentionally not honored
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_retry_delay_exponential_backoff() -> None:
    assert retry_delay(0) == 1.0
    assert retry_delay(1) == 2.0
    assert retry_delay(2) == 4.0
    assert retry_delay(3) == 8.0


def test_retry_delay_retry_after_overrides_backoff() -> None:
    assert retry_delay(0, retry_after=7.0) == 7.0
    assert retry_delay(5, retry_after=0.5) == 0.5


def test_fetch_with_retry_succeeds_without_retry() -> None:
    session = _FakeSession([_FakeResponse(404, reason="Not Found")])
    outcome = asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=3))
    assert outcome.status == 404
    assert outcome.attempts == 1
    assert session.calls == 1


def test_fetch_with_retry_retries_429_then_succeeds(monkeypatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    session = _FakeSession([
        _FakeResponse(429),
        _FakeResponse(429),
        _FakeResponse(200, headers={"Content-Length": "42"}),
    ])
    outcome = asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=3))
    assert outcome.status == 200
    assert outcome.attempts == 3
    assert outcome.content_length == 42
    assert sleeps == [1.0, 2.0]
    assert session.calls == 3


def test_fetch_with_retry_gives_up_after_max_retries(monkeypatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    session = _FakeSession([_FakeResponse(429)])
    outcome = asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=2))
    assert outcome.status == 429
    assert outcome.attempts == 3
    assert sleeps == [1.0, 2.0]
    assert session.calls == 3


def test_fetch_with_retry_honors_retry_after_header(monkeypatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    session = _FakeSession([
        _FakeResponse(429, headers={"Retry-After": "7"}),
        _FakeResponse(429, headers={"Retry-After": "120"}),
    ])
    outcome = asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=2))
    assert outcome.attempts == 3
    assert sleeps == [7.0, enumerator_mod.MAX_RETRY_AFTER_SECONDS]


def test_fetch_with_retry_disabled_by_zero_retries(monkeypatch) -> None:
    sleeps = _patch_sleep(monkeypatch)
    session = _FakeSession([_FakeResponse(429)])
    outcome = asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=0))
    assert outcome.status == 429
    assert outcome.attempts == 1
    assert sleeps == []
    assert session.calls == 1


def test_fetch_with_retry_propagates_client_errors() -> None:
    session = _FakeSession([_FakeResponse(0, error=aiohttp.ClientConnectionError("boom"))])
    with pytest.raises(aiohttp.ClientConnectionError):
        asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=3))


def test_cli_retries_flag_default_and_override() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.retries == enumerator_mod.DEFAULT_MAX_RETRIES
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt", "--retries", "0"])
    assert args.retries == 0
