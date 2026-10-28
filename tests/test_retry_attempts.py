import asyncio
import json

from durbx import enumerator as enumerator_mod
from durbx.enumerator import FetchOutcome, ScanResult, enumerate_directories
from durbx.formatter import format_result, plain_result_line, render_json_report


def _hit(attempts: int) -> ScanResult:
    return ScanResult(
        path="/admin",
        status_code=200,
        url="https://example.com/admin",
        reason="OK",
        size=42,
        attempts=attempts,
    )


def test_format_result_notes_retries_only_when_retried() -> None:
    assert "(retried 2)" in format_result(_hit(3))
    assert "retried" not in format_result(_hit(1))
    assert "retried" not in format_result(
        ScanResult(path="/a", status_code=200, url="https://example.com/a", reason="OK", size=1)
    )


def test_plain_result_line_notes_retries() -> None:
    assert "(retried 1)" in plain_result_line(_hit(2))
    assert "retried" not in plain_result_line(_hit(1))


def test_json_report_carries_attempts() -> None:
    report = json.loads(
        render_json_report([("https://example.com", [_hit(3)])], [], 0.0)
    )
    assert report["results"][0]["attempts"] == 3


def test_scan_records_fetch_attempts_on_hit(monkeypatch) -> None:
    """A hit that needed 429 retries reaches on_result with attempts=3:
    fetch_with_retry already counts attempts; scan() must carry them onto
    the ScanResult instead of dropping them."""
    captured: list[ScanResult] = []

    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=42, attempts=3)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    asyncio.run(
        enumerate_directories(
            base_url="https://example.com",
            entries=["admin"],
            threads=1,
            detect_wildcards=False,
            on_result=captured.append,
        )
    )
    assert len(captured) == 1
    assert captured[0].attempts == 3
    assert "(retried 2)" in format_result(captured[0])
