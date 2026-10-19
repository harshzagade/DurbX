import asyncio

import aiohttp
import pytest

from durbx import enumerator as enumerator_mod
from durbx.cli import build_parser
from durbx.enumerator import (
    ScanResult,
    WildcardFingerprint,
    detect_wildcard,
    enumerate_directories,
    is_wildcard_match,
    wildcard_probe_path,
)


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
    """Replays a script of responses; mimics aiohttp's `session.request(...)` API."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.calls = 0
        self.urls: list[str] = []

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def request(self, method: str, url: str, **kwargs):
        index = min(self.calls, len(self._script) - 1)
        self.calls += 1
        self.urls.append(url)
        return self._script[index]


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_wildcard_probe_path_is_random_and_safe() -> None:
    first = wildcard_probe_path()
    second = wildcard_probe_path()
    assert first != second
    assert first.startswith("durbx-wildcard-")
    assert "/" not in first
    assert " " not in first


def test_detect_wildcard_returns_none_on_404() -> None:
    session = _FakeSession([_FakeResponse(404, reason="Not Found")])
    assert asyncio.run(detect_wildcard(session, "https://example.com", max_retries=0)) is None


def test_detect_wildcard_fingerprints_soft_404() -> None:
    session = _FakeSession([_FakeResponse(200, headers={"Content-Length": "1234"})])
    fingerprint = asyncio.run(detect_wildcard(session, "https://example.com", max_retries=0))
    assert fingerprint == WildcardFingerprint(status=200, size=1234)


def test_detect_wildcard_probes_random_path() -> None:
    session = _FakeSession([_FakeResponse(404)])
    asyncio.run(detect_wildcard(session, "https://example.com", max_retries=0))
    probe_url = session.urls[0]
    assert probe_url.startswith("https://example.com/durbx-wildcard-")


def test_detect_wildcard_fail_open_on_probe_error() -> None:
    session = _FakeSession([_FakeResponse(0, error=aiohttp.ClientConnectionError("boom"))])
    assert asyncio.run(detect_wildcard(session, "https://example.com", max_retries=0)) is None


def test_detect_wildcard_retries_probe_429(monkeypatch) -> None:
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    session = _FakeSession([
        _FakeResponse(429),
        _FakeResponse(200, headers={"Content-Length": "77"}),
    ])
    fingerprint = asyncio.run(detect_wildcard(session, "https://example.com", max_retries=3))
    assert fingerprint == WildcardFingerprint(status=200, size=77)
    assert sleeps == [1.0]


def test_is_wildcard_match() -> None:
    fingerprint = WildcardFingerprint(status=200, size=100)
    matching = ScanResult(path="/x", status_code=200, url="https://example.com/x", reason="OK", size=100)
    assert is_wildcard_match(matching, fingerprint) is True
    assert is_wildcard_match(matching, None) is False
    other_status = ScanResult(path="/x", status_code=301, url="https://example.com/x", reason="Moved", size=100)
    assert is_wildcard_match(other_status, fingerprint) is False
    other_size = ScanResult(path="/x", status_code=200, url="https://example.com/x", reason="OK", size=101)
    assert is_wildcard_match(other_size, fingerprint) is False
    no_status = ScanResult(path="/x", status_code=None, url="https://example.com/x", reason="timed out", size=0)
    assert is_wildcard_match(no_status, fingerprint) is False


def test_cli_no_wildcard_flag_default_and_set() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.no_wildcard is False
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt", "--no-wildcard"])
    assert args.no_wildcard is True


def test_scan_filters_wildcard_matches() -> None:
    # The test stub answers every URL (probe included) with 200 + 2B bodies,
    # so the probe fingerprints a soft-404 and every entry gets filtered.
    _reset_stub_sessions()
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
        )
    )
    assert summary.hits == 0
    assert summary.wildcard_filtered == 2
    assert summary.fingerprint == WildcardFingerprint(status=200, size=2)
    assert summary.completed == 2


def test_scan_detect_wildcards_disabled() -> None:
    _reset_stub_sessions()
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            detect_wildcards=False,
        )
    )
    assert summary.hits == 2
    assert summary.wildcard_filtered == 0
    assert summary.fingerprint is None
