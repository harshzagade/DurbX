import aiohttp
import pytest

from durbx import cli as cli_mod
from durbx import utils as utils_mod
from durbx.cli import build_parser, main
from durbx.enumerator import ScanResult
from durbx.formatter import format_result, plain_result_line, render_results
from durbx.utils import set_no_color


def _hit() -> ScanResult:
    return ScanResult(
        path="/admin",
        status_code=200,
        url="https://example.com/admin",
        reason="OK",
        size=42,
    )


def test_format_result_colored_by_default() -> None:
    # colorama is installed in this env, so the default line really
    # carries ANSI escapes — the thing --no-color must remove.
    assert "\x1b[" in format_result(_hit())


def test_format_result_no_color_has_no_escapes() -> None:
    rendered = format_result(_hit(), color=False)
    assert "\x1b[" not in rendered
    assert rendered == plain_result_line(_hit())
    assert "/admin" in rendered and "200" in rendered and "42B" in rendered


def test_format_result_no_color_keeps_notes() -> None:
    hit = ScanResult(
        path="/a",
        status_code=200,
        url="https://example.com/a",
        reason="OK",
        size=1,
        attempts=3,
        is_directory_listing=True,
        duplicate_count=2,
    )
    rendered = format_result(hit, color=False)
    assert "\x1b[" not in rendered
    assert "(retried 2)" in rendered
    assert "(directory listing)" in rendered
    assert "(x2 identical bodies)" in rendered


def test_render_results_no_color_has_no_escapes() -> None:
    rendered = render_results([_hit()], color=False)
    assert "\x1b[" not in rendered
    assert "PATH" in rendered and "/admin" in rendered


def test_render_results_colored_by_default() -> None:
    assert "\x1b[" in render_results([_hit()])


def test_set_no_color_rebinds_console() -> None:
    original_utils_console = utils_mod.console
    try:
        new_console = set_no_color()
        assert new_console.no_color is True
        assert utils_mod.console is new_console
    finally:
        utils_mod.console = original_utils_console


def test_cli_accepts_no_color_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt", "--no-color"])
    assert args.no_color is True


def test_cli_no_color_flag_defaults_off() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt"])
    assert args.no_color is False


def test_main_with_no_color_switches_console(tmp_path) -> None:
    """Driving main() with --no-color rebinds cli's console to a
    no-color one and the scan still completes (rc 0)."""
    aiohttp.ClientSession.instances.clear()
    original_cli_console = cli_mod.console
    original_utils_console = utils_mod.console
    try:
        wordlist = tmp_path / "words.txt"
        wordlist.write_text("admin\n", encoding="utf-8")
        rc = main(["-u", "example.com", "-w", str(wordlist), "--no-color"])
        assert rc == 0
        assert cli_mod.console.no_color is True
        assert utils_mod.console.no_color is True
    finally:
        cli_mod.console = original_cli_console
        utils_mod.console = original_utils_console
