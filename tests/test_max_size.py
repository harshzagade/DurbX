import asyncio

import aiohttp
import pytest

from durbx.cli import build_parser
from durbx.enumerator import (
    ScanResult,
    enumerate_directories,
    parse_max_size,
    should_show_result,
)
from durbx.formatter import render_results


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _result(status: int, size: int) -> ScanResult:
    return ScanResult(
        path="/admin", status_code=status, url="http://x/admin", reason="OK", size=size
    )


def test_parse_max_size() -> None:
    assert parse_max_size(None) is None
    assert parse_max_size("") is None
    assert parse_max_size("100000") == 100000
    assert parse_max_size(" 100 ") == 100
    assert parse_max_size("0") == 0


def test_parse_max_size_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_max_size("abc")
    with pytest.raises(ValueError):
        parse_max_size("10x")
    with pytest.raises(ValueError):
        parse_max_size("-5")


def test_should_show_result_hides_above_max_size() -> None:
    assert should_show_result(_result(200, 200), max_size=100) is False
    # Boundary is inclusive: a body exactly N bytes is shown.
    assert should_show_result(_result(200, 100), max_size=100) is True
    assert should_show_result(_result(200, 50), max_size=100) is True
    # No filter given: everything still shows as before.
    assert should_show_result(_result(200, 200)) is True


def test_max_size_applies_with_all_codes() -> None:
    assert should_show_result(_result(403, 150), all_codes=True, max_size=100) is False
    assert should_show_result(_result(403, 77), all_codes=True, max_size=100) is True


def test_max_size_combines_with_other_size_filters() -> None:
    # A size must pass every gate: <= max-size, >= min-size, in the
    # allowlist, not in the denylist.
    assert (
        should_show_result(
            _result(200, 1234), filter_lengths=[999], match_lengths=[1234], min_size=100, max_size=2000
        )
        is True
    )
    assert (
        should_show_result(
            _result(200, 1234), filter_lengths=[999], match_lengths=[1234], min_size=100, max_size=1000
        )
        is False
    )
    assert (
        should_show_result(
            _result(200, 1234), filter_lengths=[1234], match_lengths=[1234], min_size=100, max_size=2000
        )
        is False
    )


def test_render_results_honors_max_size() -> None:
    rendered = render_results(
        [_result(200, 50), _result(200, 1234)], max_size=100
    )
    assert "50" in rendered
    assert "1234" not in rendered


def test_max_size_cli_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt", "--max-size", "100000"])
    assert args.max_size == "100000"
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.max_size is None


def test_enumerate_directories_filters_by_max_size() -> None:
    _reset_stub_sessions()
    # Stub responses all carry Content-Length "2".
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            detect_wildcards=False,
            max_size=1,
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
            max_size=2,
        )
    )
    assert summary.hits == 1
