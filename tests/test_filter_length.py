import asyncio

import aiohttp
import pytest

from durbx.cli import build_parser
from durbx.enumerator import (
    ScanResult,
    enumerate_directories,
    parse_filter_lengths,
    should_show_result,
)
from durbx.formatter import render_results


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _result(status: int, size: int) -> ScanResult:
    return ScanResult(
        path="/admin", status_code=status, url="http://x/admin", reason="OK", size=size
    )


def test_parse_filter_lengths() -> None:
    assert parse_filter_lengths(None) == []
    assert parse_filter_lengths("") == []
    assert parse_filter_lengths("1234") == [1234]
    assert parse_filter_lengths("1234, 5678") == [1234, 5678]


def test_parse_filter_lengths_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_filter_lengths("abc")
    with pytest.raises(ValueError):
        parse_filter_lengths("12x4")
    with pytest.raises(ValueError):
        parse_filter_lengths("-5")


def test_should_show_result_hides_matching_size() -> None:
    assert should_show_result(_result(200, 1234), filter_lengths=[1234]) is False
    assert should_show_result(_result(200, 999), filter_lengths=[1234]) is True
    # No filter given: everything still shows as before.
    assert should_show_result(_result(200, 1234)) is True


def test_filter_length_applies_with_all_codes() -> None:
    assert should_show_result(_result(403, 77), all_codes=True, filter_lengths=[77]) is False
    assert should_show_result(_result(403, 78), all_codes=True, filter_lengths=[77]) is True


def test_render_results_honors_filter_lengths() -> None:
    rendered = render_results(
        [_result(200, 1234), _result(200, 999)], filter_lengths=[1234]
    )
    assert "999" in rendered
    assert "1234" not in rendered


def test_filter_length_cli_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["-u", "example.com", "-w", "w.txt", "--filter-length", "1234,5678"]
    )
    assert args.filter_length == "1234,5678"
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.filter_length is None


def test_enumerate_directories_filters_by_length() -> None:
    _reset_stub_sessions()
    # Stub responses all carry Content-Length "2".
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            detect_wildcards=False,
            filter_lengths=[2],
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
            filter_lengths=[999],
        )
    )
    assert summary.hits == 1
