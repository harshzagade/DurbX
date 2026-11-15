import asyncio

import aiohttp

from durbx.cli import build_parser, main
from durbx.enumerator import ScanResult, enumerate_directories


def _run_scan(show_progress: bool) -> list[ScanResult]:
    """Run a two-entry scan against the stub session (which answers 200
    to every request) and return the collected hits."""
    aiohttp.ClientSession.instances.clear()
    hits: list[ScanResult] = []

    def on_result(result: ScanResult) -> None:
        hits.append(result)

    asyncio.run(
        enumerate_directories(
            base_url="https://example.com",
            entries=["admin", "login"],
            detect_wildcards=False,
            on_result=on_result,
            show_progress=show_progress,
        )
    )
    return hits


def test_cli_accepts_no_progress_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt", "--no-progress"])
    assert args.no_progress is True


def test_cli_no_progress_flag_defaults_off() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt"])
    assert args.no_progress is False


def test_no_progress_prints_no_bar(capsys) -> None:
    hits = _run_scan(show_progress=False)
    assert len(hits) == 2
    captured = capsys.readouterr()
    # No progress bar and no line-clear escape: with the bar off, the
    # enumerator must print nothing at all for the scan itself.
    assert captured.out == ""


def test_progress_bar_printed_by_default(capsys) -> None:
    hits = _run_scan(show_progress=True)
    assert len(hits) == 2
    captured = capsys.readouterr()
    assert "\r[" in captured.out
    assert "(2/2)" in captured.out


def test_main_with_no_progress_hides_bar(tmp_path, capsys) -> None:
    """Driving main() with --no-progress runs clean (rc 0) and emits no
    live bar. (The final summary goes through the rich console, which the
    test stubs swallow, so only the bar's absence is asserted here.)"""
    aiohttp.ClientSession.instances.clear()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(
        ["-u", "example.com", "-w", str(wordlist), "--no-wildcard", "--no-progress"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "\r[" not in captured.out
