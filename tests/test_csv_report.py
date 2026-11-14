import csv
import io

import aiohttp
import pytest

from durbx.cli import main
from durbx.enumerator import ScanResult
from durbx.formatter import CSV_FIELDNAMES, render_csv_report


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _parse_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_render_csv_report_header_and_rows() -> None:
    hits_by_target = [
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
    rows = _parse_csv(render_csv_report(hits_by_target))
    assert len(rows) == 2
    assert rows[0] == {
        "target": "https://example.com",
        "path": "/admin",
        "url": "https://example.com/admin",
        "status_code": "200",
        "reason": "OK",
        "size": "1234",
        "attempts": "2",
        "directory_listing": "false",
        "redirect_target": "",
        "duplicate_count": "1",
        "page_title": "",
        "latency_ms": "12.35",
    }
    assert rows[1]["status_code"] == "301"
    assert rows[1]["redirect_target"] == "https://example.com/new"
    assert rows[1]["latency_ms"] == ""


def test_render_csv_report_header_only_when_no_hits() -> None:
    text = render_csv_report([("https://example.com", [])])
    assert text == ",".join(CSV_FIELDNAMES) + "\n"


def test_render_csv_report_quotes_tricky_fields() -> None:
    hits_by_target = [
        (
            "https://example.com",
            [
                ScanResult(
                    path="/we,ird",
                    status_code=200,
                    url="https://example.com/we,ird",
                    reason='Moved, "Temporarily"\n(again)',
                    size=7,
                )
            ],
        )
    ]
    rows = _parse_csv(render_csv_report(hits_by_target))
    assert len(rows) == 1
    assert rows[0]["path"] == "/we,ird"
    assert rows[0]["reason"] == 'Moved, "Temporarily"\n(again)'


def test_cli_csv_flag_writes_report(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "report.csv"
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--csv",
            str(out),
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    rows = _parse_csv(out.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["target"] == "https://example.com"
    assert rows[0]["path"] == "/admin"
    assert rows[0]["status_code"] == "200"


def test_cli_csv_flag_multi_target(tmp_path) -> None:
    _reset_stub_sessions()
    targets = tmp_path / "targets.txt"
    targets.write_text("one.example\ntwo.example\n", encoding="utf-8")
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "report.csv"
    rc = main(
        [
            "--targets",
            str(targets),
            "-w",
            str(wordlist),
            "--csv",
            str(out),
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    rows = _parse_csv(out.read_text(encoding="utf-8"))
    assert {row["target"] for row in rows} == {
        "https://one.example",
        "https://two.example",
    }


def test_cli_csv_unwritable_path_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--csv",
            str(tmp_path),  # a directory: open() for writing fails
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2
