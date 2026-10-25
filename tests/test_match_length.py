import asyncio

import aiohttp
import pytest

from durbx.cli import build_parser
from durbx.enumerator import (
    ScanResult,
    enumerate_directories,
    parse_match_lengths,
    should_show_result,
)
from durbx.formatter import render_results


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _result(status: int, size: int) -> ScanResult:
    return ScanResult(
        path="/admin", status_code=status, url="http://x/admin", reason="OK", size=size
    )


def test_parse_match_lengths() -> None:
    assert parse_match_lengths(None) == []
    assert parse_match_lengths("") == []
    assert parse_match_lengths("1234") == [1234]
    assert parse_match_lengths("1234, 5678") == [1234, 5678]


def test_parse_match_lengths_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_match_lengths("abc")
    with pytest.raises(ValueError):
        parse_match_lengths("12x4")
    with pytest.raises(ValueError):
        parse_match_lengths("-5")


def test_should_show_result_keeps_only_matching_size() -> None:
    assert should_show_result(_result(200, 1234), match_lengths=[1234]) is True
    assert should_show_result(_result(200, 999), match_lengths=[1234]) is False
    # No filter given: everything still shows as before.
    assert should_show_result(_result(200, 999)) is True


def test_match_length_applies_with_all_codes() -> None:
    assert should_show_result(_result(403, 77), all_codes=True, match_lengths=[77]) is True
    assert should_show_result(_result(403, 78), all_codes=True, match_lengths=[77]) is False


def test_match_length_combines_with_filter_length() -> None:
    # A size must pass both gates: in the allowlist and not in the denylist.
    assert (
        should_show_result(_result(200, 1234), filter_lengths=[999], match_lengths=[1234])
        is True
    )
    assert (
        should_show_result(_result(200, 1234), filter_lengths=[1234], match_lengths=[1234])
        is False
    )


def test_render_results_honors_match_lengths() -> None:
    rendered = render_results(
        [_result(200, 1234), _result(200, 999)], match_lengths=[999]
    )
    assert "999" in rendered
    assert "1234" not in rendered


def test_match_length_cli_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["-u", "example.com", "-w", "w.txt", "--match-length", "1234,5678"]
    )
    assert args.match_length == "1234,5678"
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.match_length is None


def test_enumerate_directories_filters_by_match_length() -> None:
    _reset_stub_sessions()
    # Stub responses all carry Content-Length "2".
    summary = asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            detect_wildcards=False,
            match_lengths=[999],
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
            match_lengths=[2],
        )
    )
    assert summary.hits == 1
