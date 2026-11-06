import asyncio
import json

from durbx import enumerator as enumerator_mod
from durbx.cli import main
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    ScanSummary,
    enumerate_directories,
    fetch_with_retry,
)
from durbx.formatter import (
    _aggregate_tech_headers,
    format_tech_headers_summary,
    render_json_report,
)


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, limit: int) -> bytes:
        return self._body[:limit]


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self.reason = "OK"
        self.headers = headers or {"Content-Length": str(len(body))}
        self.content = _FakeContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeSession:
    def __init__(self, response) -> None:
        self._response = response

    def request(self, method: str, url: str, **kwargs):
        return self._response


def test_fetch_with_retry_captures_tech_headers() -> None:
    headers = {
        "Content-Length": "4",
        "Server": "nginx/1.18.0",
        "X-Powered-By": "PHP/8.1",
    }
    outcome = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, b"body", headers)),
        "https://example.com/a", max_retries=0))
    assert outcome.server == "nginx/1.18.0"
    assert outcome.powered_by == "PHP/8.1"
    outcome_bare = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, b"body")),
        "https://example.com/a", max_retries=0))
    assert outcome_bare.server is None
    assert outcome_bare.powered_by is None


def _fake_fetch_by_url(outcomes: dict[str, FetchOutcome]):
    async def fake_fetch(session, url, **kwargs):
        return outcomes[url.rsplit("/", 1)[-1]]
    return fake_fetch


def test_scan_tallies_tech_headers_for_displayed_hits_only(monkeypatch) -> None:
    outcomes = {
        "a": FetchOutcome(status=200, reason="OK", content_length=10,
                          attempts=1, server="nginx/1.18.0",
                          powered_by="PHP/8.1"),
        "b": FetchOutcome(status=200, reason="OK", content_length=10,
                          attempts=1, server="nginx/1.18.0"),
        # A 404 never passes the display filters, so its Server header
        # must not be tallied even though it was fetched.
        "c": FetchOutcome(status=404, reason="Not Found", content_length=10,
                          attempts=1, server="Apache/2.4"),
        # A hit with no tech headers contributes nothing.
        "d": FetchOutcome(status=200, reason="OK", content_length=10,
                          attempts=1),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _fake_fetch_by_url(outcomes))
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["a", "b", "c", "d"], threads=1,
        detect_wildcards=False))
    assert summary.hits == 3
    assert summary.tech_headers == {
        "Server": {"nginx/1.18.0": 2},
        "X-Powered-By": {"PHP/8.1": 1},
    }


def test_format_tech_headers_summary_ranking_and_empty() -> None:
    assert format_tech_headers_summary(None) is None
    assert format_tech_headers_summary({}) is None
    assert format_tech_headers_summary({"Server": {}}) is None
    assert format_tech_headers_summary({
        "Server": {"Apache/2.4": 1, "nginx/1.18.0": 2},
        "X-Powered-By": {"PHP/8.1": 1},
    }) == "Server: nginx/1.18.0 (2), Apache/2.4 (1); X-Powered-By: PHP/8.1 (1)"


def test_aggregate_tech_headers_sums_across_summaries() -> None:
    summaries = [
        ScanSummary(total=2, completed=2, hits=1,
                    tech_headers={"Server": {"nginx/1.18.0": 2}}),
        ScanSummary(total=2, completed=2, hits=1,
                    tech_headers={"Server": {"nginx/1.18.0": 1, "Apache/2.4": 1},
                                  "X-Powered-By": {"PHP/8.1": 1}}),
    ]
    assert _aggregate_tech_headers(summaries) == {
        "Server": {"nginx/1.18.0": 3, "Apache/2.4": 1},
        "X-Powered-By": {"PHP/8.1": 1},
    }


def test_json_report_carries_tech_headers() -> None:
    hits_by_target = [
        ("https://example.com", [
            ScanResult(path="/a", status_code=200, url="https://example.com/a",
                       reason="OK", size=10),
        ]),
    ]
    summaries = [ScanSummary(
        total=1, completed=1, hits=1,
        tech_headers={"Server": {"nginx/1.18.0": 1}})]
    report = json.loads(render_json_report(hits_by_target, summaries, 1.0))
    assert report["stats"]["tech_headers"] == {"Server": {"nginx/1.18.0": 1}}


def test_cli_json_report_carries_tech_headers(monkeypatch, tmp_path) -> None:
    outcomes = {
        "a": FetchOutcome(status=200, reason="OK", content_length=10,
                          attempts=1, server="nginx/1.18.0"),
        "b": FetchOutcome(status=200, reason="OK", content_length=10,
                          attempts=1, server="nginx/1.18.0",
                          powered_by="PHP/8.1"),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _fake_fetch_by_url(outcomes))
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("a\nb\n", encoding="utf-8")
    out = tmp_path / "report.json"
    rc = main(["-u", "example.com", "-w", str(wordlist), "-t", "1",
               "--json", str(out), "--no-wildcard", "-q"])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["stats"]["tech_headers"] == {
        "Server": {"nginx/1.18.0": 2},
        "X-Powered-By": {"PHP/8.1": 1},
    }
