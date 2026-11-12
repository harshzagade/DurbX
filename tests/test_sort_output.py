import aiohttp

from durbx.cli import main
from durbx.enumerator import ScanResult
from durbx.formatter import render_plain_results, sort_hits_by_path


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _hit(path: str) -> ScanResult:
    return ScanResult(
        path=path,
        status_code=200,
        url=f"https://example.com{path}",
        reason="OK",
        size=10,
    )


def test_sort_hits_by_path_case_insensitive() -> None:
    hits = [_hit("/Zebra"), _hit("/apple"), _hit("/Mango")]
    assert [hit.path for hit in sort_hits_by_path(hits)] == [
        "/apple",
        "/Mango",
        "/Zebra",
    ]


def test_sort_hits_by_path_exact_path_breaks_case_ties() -> None:
    hits = [_hit("/a"), _hit("/A")]
    assert [hit.path for hit in sort_hits_by_path(hits)] == ["/A", "/a"]


def test_sort_hits_by_path_returns_new_list() -> None:
    hits = [_hit("/b"), _hit("/a")]
    ordered = sort_hits_by_path(hits)
    assert [hit.path for hit in ordered] == ["/a", "/b"]
    assert [hit.path for hit in hits] == ["/b", "/a"]


def test_sort_hits_by_path_empty() -> None:
    assert sort_hits_by_path([]) == []


def _run_cli(tmp_path, extra: list[str]):
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("zebra\napple\nmango\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "-t",
            "1",
            "-o",
            str(out),
            "--no-wildcard",
            "-q",
            *extra,
        ]
    )
    assert rc == 0
    return [line.split()[0] for line in out.read_text(encoding="utf-8").splitlines()]


def test_cli_sort_flag_sorts_output_file(tmp_path) -> None:
    assert _run_cli(tmp_path, ["--sort"]) == ["/apple", "/mango", "/zebra"]


def test_cli_without_sort_keeps_completion_order(tmp_path) -> None:
    # One worker processes the wordlist in order, so without --sort the
    # output follows the wordlist (completion order), not the alphabet.
    assert _run_cli(tmp_path, []) == ["/zebra", "/apple", "/mango"]


def test_cli_sort_flag_sorts_json_and_csv_too(tmp_path) -> None:
    import csv
    import io
    import json

    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("zebra\napple\nmango\n", encoding="utf-8")
    json_out = tmp_path / "report.json"
    csv_out = tmp_path / "report.csv"
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "-t",
            "1",
            "--json",
            str(json_out),
            "--csv",
            str(csv_out),
            "--sort",
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert [hit["path"] for hit in report["results"]] == [
        "/apple",
        "/mango",
        "/zebra",
    ]
    rows = list(csv.DictReader(io.StringIO(csv_out.read_text(encoding="utf-8"))))
    assert [row["path"] for row in rows] == ["/apple", "/mango", "/zebra"]


def test_render_plain_results_unchanged_without_sort() -> None:
    # render_plain_results itself stays order-preserving; sorting is the
    # caller's job (cli.py, behind --sort).
    hits = [_hit("/zebra"), _hit("/apple")]
    lines = render_plain_results(hits).splitlines()
    assert [line.split()[0] for line in lines] == ["/zebra", "/apple"]
