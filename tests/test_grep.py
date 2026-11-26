import asyncio
import re

import pytest

from durbx import enumerator as enumerator_mod
from durbx.cli import build_parser
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    enumerate_directories,
    fetch_with_retry,
    parse_grep_pattern,
)
from durbx.formatter import format_result, plain_result_line


SECRET_BODY = (
    "<html><head><title>Login</title></head>"
    "<body>password=letmein <!-- TODO: remove debug secret --></body></html>"
)
CLEAN_BODY = "<html><head><title>Home</title></head><body>Welcome</body></html>"


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, limit: int) -> bytes:
        return self._body[:limit]


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self.reason = "OK"
        self.headers = headers or {"Content-Length": str(len(body))}
        self.content = _FakeContent(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False


class _FakeSession:
    def __init__(self, response) -> None:
        self._response = response

    def request(self, method: str, url: str, **kwargs):
        return self._response


def _fetch(body: bytes, pattern, status: int = 200, inspect_body: bool = True):
    return asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(status, body)), "https://example.com/admin",
        max_retries=0, inspect_body=inspect_body, grep_pattern=pattern))


def test_parse_grep_pattern() -> None:
    assert parse_grep_pattern(None) is None
    assert parse_grep_pattern("") is None
    pattern = parse_grep_pattern("password|secret")
    assert isinstance(pattern, re.Pattern)
    assert pattern.search("a secret here") is not None
    # Case-sensitive by default; (?i) opts into insensitive matching.
    assert parse_grep_pattern("PASSWORD").search("password") is None
    assert parse_grep_pattern("(?i)PASSWORD").search("password") is not None


def test_parse_grep_pattern_rejects_junk() -> None:
    with pytest.raises(ValueError):
        parse_grep_pattern("[a-")
    with pytest.raises(ValueError):
        parse_grep_pattern("(?P<")


def test_fetch_with_retry_tags_matching_body() -> None:
    body = SECRET_BODY.encode("utf-8")
    outcome = _fetch(body, parse_grep_pattern("password=\\w+"))
    assert outcome.grep_match is True
    # A pattern that does not occur in the body tags nothing.
    outcome_clean = _fetch(body, parse_grep_pattern("api[_-]?key"))
    assert outcome_clean.grep_match is False
    # No pattern given: never matches.
    outcome_none = _fetch(body, None)
    assert outcome_none.grep_match is False
    # Non-200 bodies are never read, so they never match.
    outcome_404 = _fetch(body, parse_grep_pattern("password"), status=404)
    assert outcome_404.grep_match is False
    # Without body inspection there is no window to search.
    outcome_no_inspect = _fetch(
        body, parse_grep_pattern("password"), inspect_body=False
    )
    assert outcome_no_inspect.grep_match is False


def test_grep_note_in_terminal_and_plain_output() -> None:
    matched = ScanResult(path="/admin", status_code=200, url="https://example.com/admin",
                         reason="OK", size=512, grep_match=True, grep_pattern="password|secret")
    assert "(grep: password|secret)" in format_result(matched)
    assert "(grep: password|secret)" in plain_result_line(matched)
    unmatched = ScanResult(path="/admin", status_code=200, url="https://example.com/admin",
                           reason="OK", size=512)
    assert "(grep:" not in plain_result_line(unmatched)


def test_grep_note_truncates_long_patterns() -> None:
    long_pattern = "x" * 80
    matched = ScanResult(path="/admin", status_code=200, url="https://example.com/admin",
                         reason="OK", size=512, grep_match=True, grep_pattern=long_pattern)
    line = plain_result_line(matched)
    assert "(grep: " + "x" * 60 + "...)" in line
    assert "x" * 80 not in line


def test_scan_carries_grep_onto_hits(monkeypatch) -> None:
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=512,
                            attempts=1, grep_match=True)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    seen: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin"], threads=1, detect_wildcards=False,
        grep_pattern=parse_grep_pattern("password|secret"),
        on_result=seen.append))
    assert summary.hits == 1
    assert seen[0].grep_match is True
    assert seen[0].grep_pattern == "password|secret"


def test_grep_is_tag_only_not_a_filter(monkeypatch) -> None:
    # A non-matching hit still shows: --grep tags, it never hides.
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=512,
                            attempts=1, grep_match=False)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin"], threads=1, detect_wildcards=False,
        grep_pattern=parse_grep_pattern("password|secret")))
    assert summary.hits == 1


def test_grep_cli_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt", "--grep", "password|secret"])
    assert args.grep == "password|secret"
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.grep is None
