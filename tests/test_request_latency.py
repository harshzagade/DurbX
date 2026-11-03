import asyncio
import json

from durbx import enumerator as enumerator_mod
from durbx.enumerator import FetchOutcome, ScanResult, enumerate_directories
from durbx.formatter import render_json_report, render_latency_summary


def _hit(path: str, latency: float | None, status: int = 200) -> ScanResult:
    return ScanResult(
        path=path,
        status_code=status,
        url=f"https://example.com{path}",
        reason="OK",
        size=10,
        latency_ms=latency,
    )


def test_result_defaults_to_unmeasured_latency() -> None:
    hit = ScanResult(
        path="/a", status_code=200, url="https://example.com/a",
        reason="OK", size=10,
    )
    assert hit.latency_ms is None


def test_scan_measures_request_latency(monkeypatch) -> None:
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=0, attempts=1)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    seen: list = []
    asyncio.run(
        enumerate_directories(
            "https://example.com", ["a"], threads=1,
            detect_wildcards=False, on_result=seen.append,
        )
    )
    assert len(seen) == 1
    assert seen[0].latency_ms is not None
    assert seen[0].latency_ms >= 0


def test_latency_summary_formats_average_and_slowest() -> None:
    hits = [_hit("/a", 10.0), _hit("/b", 50.0), _hit("/c", 30.0), _hit("/d", 5.0)]
    assert render_latency_summary(hits) == (
        "avg 23.8ms; slowest: /b (50.0ms), /c (30.0ms), /a (10.0ms)"
    )


def test_latency_summary_ignores_unmeasured_hits() -> None:
    hits = [_hit("/a", None), _hit("/b", 20.0)]
    assert render_latency_summary(hits) == "avg 20.0ms; slowest: /b (20.0ms)"
    assert render_latency_summary([_hit("/a", None)]) is None
    assert render_latency_summary([]) is None


def test_json_report_carries_latency_stats() -> None:
    hits = [_hit("/a", 10.0), _hit("/b", 50.0), _hit("/c", 30.0), _hit("/d", 5.0)]
    report = json.loads(render_json_report([("https://example.com", hits)], [], 1.0))
    assert report["stats"]["avg_latency_ms"] == 23.75
    assert report["stats"]["slowest_hits"] == [
        {"path": "/b", "status_code": 200, "latency_ms": 50.0},
        {"path": "/c", "status_code": 200, "latency_ms": 30.0},
        {"path": "/a", "status_code": 200, "latency_ms": 10.0},
    ]
    assert report["results"][0]["latency_ms"] == 10.0


def test_json_report_latency_stats_empty_without_measurements() -> None:
    hits = [_hit("/a", None)]
    report = json.loads(render_json_report([("https://example.com", hits)], [], 1.0))
    assert report["stats"]["avg_latency_ms"] is None
    assert report["stats"]["slowest_hits"] == []
    assert report["results"][0]["latency_ms"] is None
