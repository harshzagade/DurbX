from durbx.enumerator import ScanResult, ScanSummary, load_wordlist, normalize_target, parse_status_codes
from durbx.formatter import format_result, render_results
from durbx.cli import build_parser


def test_normalize_target_adds_https_scheme() -> None:
    assert normalize_target("example.com") == "https://example.com"


def test_load_wordlist_deduplicates_entries(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\nadmin\n# skip\nlogin\n", encoding="utf-8")
    assert load_wordlist(str(wordlist)) == ["admin", "login"]


def test_render_results_filters_404_by_default() -> None:
    rendered = render_results(
        [
            ScanResult(path="/admin", status_code=200, url="https://example.com/admin", reason="OK", size=12),
            ScanResult(path="/missing", status_code=404, url="https://example.com/missing", reason="Not Found", size=0),
            ScanResult(path="/forbidden", status_code=403, url="https://example.com/forbidden", reason="Forbidden", size=0),
        ]
    )
    assert "/admin" in rendered
    assert "/missing" not in rendered
    assert "/forbidden" not in rendered


def test_cli_uses_url_and_wordlist_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.url == "example.com"
    assert args.wordlist == "custom.txt"


def test_parse_status_codes_parses_comma_list() -> None:
    assert parse_status_codes("200, 403") == [200, 403]


def test_format_result_shows_url_for_accessible_codes() -> None:
    rendered = format_result(ScanResult(path="/admin", status_code=200, url="https://example.com/admin", reason="OK", size=99))
    assert "-> https://example.com/admin" in rendered


def test_format_result_keeps_size_text() -> None:
    rendered = format_result(ScanResult(path="/admin", status_code=403, url="https://example.com/admin", reason="Forbidden", size=42))
    assert "42B" in rendered


def test_scan_summary_dataclass() -> None:
    summary = ScanSummary(total=10, completed=10, hits=2)
    assert summary.hits == 2
