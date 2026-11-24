import asyncio

import aiohttp
import pytest

from durbx.cli import build_parser
from durbx.enumerator import (
    ScanResult,
    enumerate_directories,
    parse_min_size,
    should_show_result,
)
from durbx.formatter import render_results


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _result(status: int, size: int) -> ScanResult:
    return ScanResult(
        path="/admin", status_code=status, url="http://x/admin", reason="OK", size=size
    )


def test_parse_min_size() -> None:
    assert parse_min_size(None) is None
    assert parse_min_size("") is None
    assert parse_min_size("100") == 100
    assert parse_min_size(" 100 ") == 100
    assert parse_min_size("0") == 0


def test_parse_min_size_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_min_size("abc")
    with pytest.raises(ValueError):
        parse_min_size("10x")
    with pytest.raises(ValueError):
        parse_min_size("-5")


def test_should_show_result_hides_below_min_size() -> None:
    assert should_show_result(_result(200, 50), min_size=100) is False
    # Boundary is inclusive: a body exactly N bytes is shown.
    assert should_show_result(_result(200, 100), min_size=100) is True
    assert should_show_result(_result(200, 200), min_size=100) is True
    # No filter given: everything still shows as before.
    assert should_show_result(_result(200, 50)) is True


def test_min_size_applies_with_all_codes() -> None:
    assert should_show_result(_result(403, 77), all_codes=True, min_size=100) is False
    assert should_show_result(_result(403, 150), all_codes=True, min_size=100) is True


def test_min_size_combines_with_other_size_filters() -> None:
    # A size must pass every gate: >= min-size, in the allowlist, not in
    # the denylist.
    assert (
        should_show_result(
            _result(200, 1234), filter_lengths=[999], match_lengths=[1234], min_size=100
        )
        is True
    )
    assert (
        should_show_result(
            _result(200, 50), filter_lengths=[999], match_lengths=[50], min_size=100
        )
        is False
    )
    assert (
        should_show_result(
            _result(200, 1234), filter_lengths=[1234], match_lengths=[1234], min_size=100
        )
        is False
    )


def test_render_results_honors_min_size() -> None:
    rendered = render_results(
        [_result(200, 1234), _result(200, 50)], min_size=100
    )
    assert "1234" in rendered
    assert "50" not in rendered


def test_min_size_cli_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt", "--min-size", "100"])
    assert args.min_size == "100"
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.min_size is None


def test_enumerate_directories_filters_by_min_size() -> None:
    _reset_stub_sessions()
    # Stub responses all carry Content-Length "2".
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            detect_wildcards=False,
            min_size=3,
        )
    )
    assert summary.hits == 0

    _reset_stub_sessions()
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin"],
            threads=1,
            detect_wildcards=False,
            min_size=2,
        )
    )
    assert summary.hits == 1
