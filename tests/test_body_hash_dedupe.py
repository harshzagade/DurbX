import asyncio
import hashlib
import json

from durbx import enumerator as enumerator_mod
from durbx.cli import main
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    ScanSummary,
    enumerate_directories,
    fetch_with_retry,
    hash_body_snippet,
)
from durbx.formatter import format_result, plain_result_line, render_json_report


BODY_A = b"<html><body><h1>Same template</h1><p>hello</p></body></html>"
BODY_B = b"<html><body><h1>Different page</h1><p>world</p></body></html>"
HASH_A = hashlib.sha256(BODY_A.decode("utf-8").encode("utf-8")).hexdigest()
HASH_B = hashlib.sha256(BODY_B.decode("utf-8").encode("utf-8")).hexdigest()


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


class _FakeResponseNoBody(_FakeResponse):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        del self.content


class _FakeSession:
    def __init__(self, response) -> None:
        self._response = response

    def request(self, method: str, url: str, **kwargs):
        return self._response


def test_hash_body_snippet_known_value_and_empty() -> None:
    assert hash_body_snippet(BODY_A.decode("utf-8")) == HASH_A
    assert hash_body_snippet("") is None


def test_fetch_with_retry_body_hash_only_for_inspected_200() -> None:
    outcome = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, BODY_A)), "https://example.com/a",
        max_retries=0, inspect_body=True))
    assert outcome.body_hash == HASH_A
    outcome_no_inspect = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, BODY_A)), "https://example.com/a",
        max_retries=0))
    assert outcome_no_inspect.body_hash is None
    outcome_404 = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(404, BODY_A)), "https://example.com/a",
        max_retries=0, inspect_body=True))
    assert outcome_404.body_hash is None
    outcome_empty = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, b"")), "https://example.com/a",
        max_retries=0, inspect_body=True))
    assert outcome_empty.body_hash is None
    outcome_no_reader = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponseNoBody(200)), "https://example.com/a",
        max_retries=0, inspect_body=True))
    assert outcome_no_reader.body_hash is None


def _fake_fetch_by_url(outcomes: dict[str, FetchOutcome]):
    async def fake_fetch(session, url, **kwargs):
        return outcomes[url.rsplit("/", 1)[-1]]
    return fake_fetch


def test_scan_collapses_identical_bodies(monkeypatch) -> None:
    outcomes = {
        "a": FetchOutcome(status=200, reason="OK", content_length=len(BODY_A),
                          attempts=1, body_hash=HASH_A),
        "b": FetchOutcome(status=200, reason="OK", content_length=len(BODY_A),
                          attempts=1, body_hash=HASH_A),
        "c": FetchOutcome(status=200, reason="OK", content_length=len(BODY_B),
                          attempts=1, body_hash=HASH_B),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _fake_fetch_by_url(outcomes))
    shown: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["a", "b", "c"], threads=1,
        detect_wildcards=False, on_result=shown.append))
    assert [result.path for result in shown] == ["/a", "/c"]
    assert summary.hits == 2
    assert summary.duplicate_bodies_collapsed == 1
    assert summary.duplicate_body_counts == {HASH_A: 2, HASH_B: 1}


def test_scan_keeps_distinct_bodies(monkeypatch) -> None:
    outcomes = {
        "a": FetchOutcome(status=200, reason="OK", content_length=len(BODY_A),
                          attempts=1, body_hash=HASH_A),
        "c": FetchOutcome(status=200, reason="OK", content_length=len(BODY_B),
                          attempts=1, body_hash=HASH_B),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _fake_fetch_by_url(outcomes))
    shown: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["a", "c"], threads=1,
        detect_wildcards=False, on_result=shown.append))
    assert len(shown) == 2
    assert summary.hits == 2
    assert summary.duplicate_bodies_collapsed == 0
    assert summary.duplicate_body_counts == {HASH_A: 1, HASH_B: 1}


def test_scan_does_not_dedupe_non_200_or_hashless(monkeypatch) -> None:
    # Two 403s sharing a hash still both show: dedupe is a 200-body rule.
    outcomes = {
        "a": FetchOutcome(status=403, reason="Forbidden", content_length=10,
                          attempts=1, body_hash=HASH_A),
        "b": FetchOutcome(status=403, reason="Forbidden", content_length=10,
                          attempts=1, body_hash=HASH_A),
        # Two 200s with no hash (e.g. empty bodies) are never collapsed.
        "c": FetchOutcome(status=200, reason="OK", content_length=0,
                          attempts=1, body_hash=None),
        "d": FetchOutcome(status=200, reason="OK", content_length=0,
                          attempts=1, body_hash=None),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _fake_fetch_by_url(outcomes))
    shown: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["a", "b", "c", "d"], threads=1,
        detect_wildcards=False, status_filter=[200, 403],
        on_result=shown.append))
    assert [result.path for result in shown] == ["/a", "/b", "/c", "/d"]
    assert summary.hits == 4
    assert summary.duplicate_bodies_collapsed == 0


def test_duplicate_note_in_terminal_and_plain_output() -> None:
    collapsed = ScanResult(path="/a", status_code=200, url="https://example.com/a",
                           reason="OK", size=64, body_hash=HASH_A, duplicate_count=3)
    assert "(x3 identical bodies)" in format_result(collapsed)
    assert "(x3 identical bodies)" in plain_result_line(collapsed)
    plain = ScanResult(path="/a", status_code=200, url="https://example.com/a",
                       reason="OK", size=64, body_hash=HASH_A)
    assert "(x3 identical bodies)" not in plain_result_line(plain)
    assert "identical bodies" not in plain_result_line(plain)


def test_json_report_carries_duplicate_counts() -> None:
    hits_by_target = [
        ("https://example.com", [
            ScanResult(path="/a", status_code=200, url="https://example.com/a",
                       reason="OK", size=64, body_hash=HASH_A, duplicate_count=2),
        ]),
    ]
    summaries = [ScanSummary(
        total=3, completed=3, hits=1, duplicate_bodies_collapsed=1,
        duplicate_body_counts={HASH_A: 2})]
    report = json.loads(render_json_report(hits_by_target, summaries, 1.0))
    assert report["stats"]["duplicate_bodies_collapsed"] == 1
    assert report["results"][0]["duplicate_count"] == 2


def test_cli_json_report_finalizes_duplicate_count(monkeypatch, tmp_path) -> None:
    outcomes = {
        "a": FetchOutcome(status=200, reason="OK", content_length=len(BODY_A),
                          attempts=1, body_hash=HASH_A),
        "b": FetchOutcome(status=200, reason="OK", content_length=len(BODY_A),
                          attempts=1, body_hash=HASH_A),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _fake_fetch_by_url(outcomes))
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("a\nb\n", encoding="utf-8")
    out = tmp_path / "report.json"
    rc = main(["-u", "example.com", "-w", str(wordlist), "-t", "1",
               "--json", str(out), "--no-wildcard", "-q"])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["stats"]["hits"] == 1
    assert report["stats"]["duplicate_bodies_collapsed"] == 1
    assert len(report["results"]) == 1
    assert report["results"][0]["path"] == "/a"
    assert report["results"][0]["duplicate_count"] == 2
