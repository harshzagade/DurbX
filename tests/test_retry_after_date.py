import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from durbx import enumerator as enumerator_mod
from durbx.enumerator import fetch_with_retry, parse_retry_after


def _http_date(seconds_from_now: float) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)
    return format_datetime(moment, usegmt=True)


class _FakeResponse:
    def __init__(self, status: int, reason: str = "OK", headers: dict | None = None) -> None:
        self.status = status
        self.reason = reason
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeSession:
    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0

    def request(self, method: str, url: str, **kwargs):
        index = min(self.calls, len(self._script) - 1)
        self.calls += 1
        return self._script[index]


def test_parse_retry_after_http_date() -> None:
    # ~30s in the future: allow a second of test-run drift.
    assert parse_retry_after(_http_date(30)) == pytest.approx(30, abs=1.0)
    # A date already in the past means retry immediately, not backoff.
    assert parse_retry_after(_http_date(-60)) == 0.0
    # Far-future dates are clamped like large delta-seconds values.
    assert parse_retry_after(_http_date(3600)) == enumerator_mod.MAX_RETRY_AFTER_SECONDS
    # A date without a zone is read as GMT (RFC 9110).
    naive = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20)).replace(
        "+0000", ""
    ).strip()
    assert parse_retry_after(naive) == pytest.approx(20, abs=1.0)
    assert parse_retry_after("Wed, 99 Oct 2026 07:28:00 GMT") is None


def test_fetch_with_retry_honors_http_date_retry_after(monkeypatch) -> None:
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    session = _FakeSession([
        _FakeResponse(429, headers={"Retry-After": _http_date(45)}),
        _FakeResponse(200, headers={"Content-Length": "7"}),
    ])
    outcome = asyncio.run(fetch_with_retry(session, "https://example.com/x", max_retries=2))
    assert outcome.status == 200
    assert outcome.attempts == 2
    assert sleeps == [pytest.approx(45, abs=1.0)]
