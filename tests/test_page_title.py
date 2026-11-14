import asyncio

from durbx import enumerator as enumerator_mod
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    enumerate_directories,
    extract_page_title,
    fetch_with_retry,
)
from durbx.formatter import format_result, plain_result_line


TITLED_BODY = (
    "<html><head><title>Admin Panel</title></head>"
    "<body>Hello</body></html>"
)
MULTILINE_BODY = (
    "<html><head><TITLE>\n  Welcome   to\n  Example\n</TITLE></head></html>"
)
UNTITLED_BODY = "<html><head></head><body>No title here</body></html>"


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


def test_extract_page_title_basic_and_case_insensitive() -> None:
    assert extract_page_title(TITLED_BODY) == "Admin Panel"
    # Tag name case does not matter; inner whitespace collapses.
    assert extract_page_title(MULTILINE_BODY) == "Welcome to Example"


def test_extract_page_title_missing_or_empty() -> None:
    assert extract_page_title(UNTITLED_BODY) is None
    assert extract_page_title("") is None
    assert extract_page_title("<html><head><title>   </title></head></html>") is None
    # A title with no closing tag is not a title.
    assert extract_page_title("<html><head><title>Unclosed") is None


def test_fetch_with_retry_captures_title_only_when_inspecting() -> None:
    body = TITLED_BODY.encode("utf-8")
    outcome = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, body)), "https://example.com/admin",
        max_retries=0, inspect_body=True))
    assert outcome.page_title == "Admin Panel"
    outcome_no_inspect = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, body)), "https://example.com/admin",
        max_retries=0))
    assert outcome_no_inspect.page_title is None
    # Non-200 bodies are never read, so they never carry a title.
    outcome_404 = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(404, body)), "https://example.com/nope",
        max_retries=0, inspect_body=True))
    assert outcome_404.page_title is None


def test_title_note_in_terminal_and_plain_output() -> None:
    titled = ScanResult(path="/admin", status_code=200, url="https://example.com/admin",
                        reason="OK", size=512, page_title="Admin Panel")
    assert "(title: Admin Panel)" in format_result(titled)
    assert "(title: Admin Panel)" in plain_result_line(titled)
    untitled = ScanResult(path="/admin", status_code=200, url="https://example.com/admin",
                          reason="OK", size=512)
    assert "(title:" not in plain_result_line(untitled)


def test_title_note_truncates_long_titles() -> None:
    long_title = "A" * 80
    titled = ScanResult(path="/admin", status_code=200, url="https://example.com/admin",
                        reason="OK", size=512, page_title=long_title)
    line = plain_result_line(titled)
    assert "(title: " + "A" * 60 + "...)" in line
    assert "A" * 80 not in line


def test_scan_carries_page_title_onto_hits(monkeypatch) -> None:
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=512,
                            attempts=1, page_title="Admin Panel")

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    seen: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin"], threads=1, detect_wildcards=False,
        on_result=seen.append))
    assert summary.hits == 1
    assert seen[0].page_title == "Admin Panel"
