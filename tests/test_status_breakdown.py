import asyncio
import json

from durbx import enumerator as enumerator_mod
from durbx.enumerator import (
    FetchOutcome,
    ScanSummary,
    enumerate_directories,
)
from durbx.formatter import format_status_breakdown, render_json_report


def test_summary_defaults_to_empty_status_counts() -> None:
    summary = ScanSummary(total=10, completed=10, hits=2)
    assert summary.status_counts == {}


def test_format_status_breakdown_sorts_codes() -> None:
    assert format_status_breakdown({403: 1, 200: 3}) == "200: 3, 403: 1"
    assert format_status_breakdown({}) == ""
    assert format_status_breakdown(None) == ""


def test_json_report_aggregates_status_counts() -> None:
    summaries = [
        ScanSummary(total=10, completed=10, hits=3, status_counts={200: 2, 403: 1}),
        ScanSummary(total=5, completed=5, hits=1, status_counts={200: 1}),
    ]
    report = json.loads(render_json_report([], summaries, 1.0))
    # JSON object keys are strings; the per-code totals still add up.
    assert report["stats"]["status_counts"] == {"200": 3, "403": 1}


def test_json_report_empty_breakdown_when_no_hits() -> None:
    report = json.loads(
        render_json_report([], [ScanSummary(total=5, completed=5, hits=0)], 1.0)
    )
    assert report["stats"]["status_counts"] == {}


def _run_scan_with_statuses(monkeypatch, statuses: list[int], **kwargs):
    """Drive enumerate_directories with one fake response per entry."""
    entries = ["a", "b", "c", "d"][: len(statuses)]
    responses = {
        entry: FetchOutcome(status=status, reason="OK", content_length=0, attempts=1)
        for entry, status in zip(entries, statuses)
    }

    async def fake_fetch(session, url, **kwargs):
        return responses[url.rsplit("/", 1)[-1]]

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    return asyncio.run(
        enumerate_directories(
            "https://example.com",
            entries,
            threads=1,
            detect_wildcards=False,
            on_result=lambda result: None,
            **kwargs,
        )
    )


def test_scan_counts_hits_per_status(monkeypatch) -> None:
    summary = _run_scan_with_statuses(monkeypatch, [200, 403, 200], all_codes=True)
    assert summary.hits == 3
    assert summary.status_counts == {200: 2, 403: 1}


def test_scan_excludes_non_hits_from_breakdown(monkeypatch) -> None:
    # Default filters show only 200: the 404 is not a hit and must not
    # appear in the breakdown.
    summary = _run_scan_with_statuses(monkeypatch, [200, 404])
    assert summary.hits == 1
    assert summary.status_counts == {200: 1}
