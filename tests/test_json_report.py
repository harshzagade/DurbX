import json

import aiohttp
import pytest

from durbx.cli import main
from durbx.enumerator import ScanResult, ScanSummary
from durbx.formatter import render_json_report


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_render_json_report_structure() -> None:
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
                )
            ],
        ),
        ("https://other.com", []),
    ]
    summaries = [
        ScanSummary(total=10, completed=10, hits=1, wildcard_filtered=2),
        ScanSummary(total=5, completed=5, hits=0, wildcard_filtered=0),
    ]
    report = json.loads(render_json_report(hits_by_target, summaries, 12.345))
    assert report["tool"] == "DurbX"
    assert report["stats"]["targets"] == 2
    assert report["stats"]["completed"] == 15
    assert report["stats"]["total"] == 15
    assert report["stats"]["hits"] == 1
    assert report["stats"]["wildcard_filtered"] == 2
    assert report["stats"]["duration_seconds"] == 12.35
    assert len(report["results"]) == 1
    hit = report["results"][0]
    assert hit == {
        "target": "https://example.com",
        "path": "/admin",
        "url": "https://example.com/admin",
        "status_code": 200,
        "reason": "OK",
        "size": 1234,
        "attempts": 1,
        "directory_listing": False,
    }


def test_cli_json_flag_writes_report(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "report.json"
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--json",
            str(out),
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tool"] == "DurbX"
    assert report["stats"]["targets"] == 1
    assert report["stats"]["hits"] == 1
    assert report["stats"]["completed"] == report["stats"]["total"] == 1
    hit = report["results"][0]
    assert hit["target"] == "https://example.com"
    assert hit["path"] == "/admin"
    assert hit["status_code"] == 200


def test_cli_json_flag_multi_target_groups_by_target(tmp_path) -> None:
    _reset_stub_sessions()
    targets = tmp_path / "targets.txt"
    targets.write_text("one.example\ntwo.example\n", encoding="utf-8")
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "report.json"
    rc = main(
        [
            "--targets",
            str(targets),
            "-w",
            str(wordlist),
            "--json",
            str(out),
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["stats"]["targets"] == 2
    assert {hit["target"] for hit in report["results"]} == {
        "https://one.example",
        "https://two.example",
    }


def test_cli_json_unwritable_path_exit_2(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--json",
            str(tmp_path),  # a directory: open() for writing fails
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 2
