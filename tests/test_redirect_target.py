import asyncio
import json

from durbx import enumerator as enumerator_mod
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    enumerate_directories,
    fetch_with_retry,
)
from durbx.formatter import (
    format_result,
    plain_result_line,
    render_json_report,
)


class _FakeResponse:
    def __init__(self, status: int, headers: dict | None = None) -> None:
        self.status = status
        self.reason = "Moved" if 300 <= status < 400 else "OK"
        self.headers = headers or {"Content-Length": "0"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeSession:
    def __init__(self, response) -> None:
        self._response = response

    def request(self, method: str, url: str, **kwargs):
        return self._response


def _fetch(status: int, headers: dict | None = None) -> FetchOutcome:
    return asyncio.run(
        fetch_with_retry(
            _FakeSession(_FakeResponse(status, headers)),
            "https://example.com/old",
            max_retries=0,
        )
    )


def test_fetch_captures_location_on_3xx_only() -> None:
    outcome = _fetch(301, {"Location": "https://example.com/new",
                           "Content-Length": "0"})
    assert outcome.redirect_target == "https://example.com/new"
    assert _fetch(301, {"Content-Length": "0"}).redirect_target is None
    # A Location header on a non-3xx response is not a redirect target.
    assert _fetch(200, {"Location": "https://example.com/new",
                        "Content-Length": "0"}).redirect_target is None


def test_formatter_shows_redirect_target_not_requested_url() -> None:
    hit = ScanResult(
        path="/old", status_code=301, url="https://example.com/old",
        reason="Moved", size=0, redirect_target="https://example.com/new",
    )
    assert "-> https://example.com/new" in format_result(hit)
    assert "-> https://example.com/new" in plain_result_line(hit)
    assert "example.com/old" not in format_result(hit)


def test_formatter_falls_back_to_url_without_target() -> None:
    hit = ScanResult(
        path="/old", status_code=301, url="https://example.com/old",
        reason="Moved", size=0,
    )
    assert "-> https://example.com/old" in plain_result_line(hit)


def test_formatter_shows_target_for_other_3xx() -> None:
    hit = ScanResult(
        path="/tmp", status_code=307, url="https://example.com/tmp",
        reason="Temporary Redirect", size=0,
        redirect_target="/login",
    )
    assert "-> /login" in plain_result_line(hit)
    plain_200 = ScanResult(
        path="/ok", status_code=200, url="https://example.com/ok",
        reason="OK", size=10,
    )
    assert "-> https://example.com/ok" in plain_result_line(plain_200)


def test_scan_carries_redirect_target_to_hit(monkeypatch) -> None:
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(
            status=301, reason="Moved", content_length=0, attempts=1,
            redirect_target="https://example.com/new",
        )

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    seen: list = []
    asyncio.run(
        enumerate_directories(
            "https://example.com", ["old"], threads=1,
            detect_wildcards=False, all_codes=True,
            on_result=seen.append,
        )
    )
    assert len(seen) == 1
    assert seen[0].redirect_target == "https://example.com/new"


def test_json_report_carries_redirect_target() -> None:
    hit = ScanResult(
        path="/old", status_code=301, url="https://example.com/old",
        reason="Moved", size=0, redirect_target="https://example.com/new",
    )
    report = json.loads(render_json_report(
        [("https://example.com", [hit])], [], 0.5))
    assert report["results"][0]["redirect_target"] == "https://example.com/new"
