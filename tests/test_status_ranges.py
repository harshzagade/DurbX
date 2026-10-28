import pytest

from durbx.cli import main
from durbx.enumerator import ScanResult, parse_status_codes, should_show_result


def _result(status: int) -> ScanResult:
    return ScanResult(
        path="/x", status_code=status, url=f"https://example.com/x", reason="OK", size=1
    )


def test_parse_status_codes_expands_range() -> None:
    assert parse_status_codes("200-202") == [200, 201, 202]


def test_parse_status_codes_mixes_singles_and_ranges() -> None:
    assert parse_status_codes("200,301,500-502") == [200, 301, 500, 501, 502]


def test_parse_status_codes_dedupes_overlap() -> None:
    assert parse_status_codes("200,200-202") == [200, 201, 202]


def test_parse_status_codes_rejects_bad_ranges() -> None:
    for bad in ("299-200", "200-", "-299", "200-299-300", "abc-def", "99-200", "200-600"):
        with pytest.raises(ValueError):
            parse_status_codes(bad)


def test_parse_status_codes_still_rejects_junk_singles() -> None:
    with pytest.raises(ValueError):
        parse_status_codes("200,abc")


def test_status_range_filters_results() -> None:
    allow = parse_status_codes("200-299")
    assert should_show_result(_result(204), status_filter=allow)
    assert not should_show_result(_result(404), status_filter=allow)
    deny = parse_status_codes("500-599")
    assert not should_show_result(_result(503), exclude_filter=deny)
    assert should_show_result(_result(200), exclude_filter=deny)


def test_cli_rejects_bad_status_range(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "example.com", "-w", str(wordlist), "--status", "299-200"]) == 2
