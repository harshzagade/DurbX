import json

import aiohttp
import pytest

from durbx.cli import main
from durbx.enumerator import ScanResult
from durbx.formatter import render_json_report, render_jsonl_report
from durbx.enumerator import ScanSummary


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _hits_by_target() -> list[tuple[str, list[ScanResult]]]:
    return [
        (
            "https://example.com",
            [
                ScanResult(
                    path="/admin",
                    status_code=200,
                    url="https://example.com/admin",
                    reason="OK",
                    size=1234,
                    attempts=2,
                    latency_ms=12.345,
                ),
                ScanResult(
                    path="/old",
                    status_code=301,
                    url="https://example.com/old",
                    reason="Moved Permanently",
                    size=0,
                    redirect_target="https://example.com/new",
                ),
            ],
        ),
        ("https://other.com", []),
    ]


def _parse_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines()]


def test_render_jsonl_report_one_object_per_hit() -> None:
    text = render_jsonl_report(_hits_by_target())
    rows = _parse_jsonl(text)
    assert len(rows) == 2
    assert rows[0] == {
        "target": "https://example.com",
        "path": "/admin",
        "url": "https://example.com/admin",
        "status_code": 200,
        "reason": "OK",
        "size": 1234,
        "attempts": 2,
        "directory_listing": False,
        "redirect_target": None,
        "duplicate_count": 1,
        "page_title": None,
        "latency_ms": 12.35,
    }
    assert rows[1]["status_code"] == 301
    assert rows[1]["redirect_target"] == "https://example.com/new"
    assert rows[1]["latency_ms"] is None


def test_render_jsonl_report_trailing_newline() -> None:
    assert render_jsonl_report(_hits_by_target()).endswith("\n")


def test_render_jsonl_report_empty_when_no_hits() -> None:
    assert render_jsonl_report([("https://example.com", [])]) == ""


def test_jsonl_fields_match_json_report() -> None:
    """The JSONL per-hit dicts are exactly the JSON report's result dicts."""
    summaries = [
        ScanSummary(
            total=2,
            completed=2,
            hits=2,
            wildcard_filtered=0,
            directory_listings=0,
            duplicate_bodies_collapsed=0,
        )
    ]
    json_hits = json.loads(
        render_json_report(_hits_by_target(), summaries, 1.23)
    )["results"]
    jsonl_hits = _parse_jsonl(render_jsonl_report(_hits_by_target()))
    assert jsonl_hits == json_hits


def test_cli_jsonl_flag_writes_report(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "report.jsonl"
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--jsonl",
            str(out),
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    rows = _parse_jsonl(out.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["target"] == "https://example.com"
    assert rows[0]["path"] == "/admin"
    assert rows[0]["status_code"] == 200


def test_cli_jsonl_flag_with_sort(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("zebra\napple\nmango\n", encoding="utf-8")
    out = tmp_path / "report.jsonl"
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "-t",
            "1",
            "--jsonl",
            str(out),
            "--sort",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    rows = _parse_jsonl(out.read_text(encoding="utf-8"))
    assert [row["path"] for row in rows] == ["/apple", "/mango", "/zebra"]


def test_cli_jsonl_unwritable_path_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--jsonl",
            str(tmp_path),  # a directory: open() for writing fails
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2
