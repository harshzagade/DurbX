import asyncio

from durbx import enumerator as enumerator_mod
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    enumerate_directories,
    fetch_with_retry,
    looks_like_directory_listing,
)
from durbx.formatter import format_result, plain_result_line


APACHE_BODY = (
    "<html><head><title>Index of /files/</title></head>"
    "<body><h1>Index of /files/</h1><a href=\"../\">Parent Directory</a></body></html>"
)
NGINX_BODY = (
    "<html><head><title>index of /downloads/</title></head><body></body></html>"
)
NORMAL_BODY = "<html><head><title>Welcome</title></head><body>Hello</body></html>"


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


class _FakeResponseNoBody(_FakeResponse):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        del self.content


class _FakeSession:
    def __init__(self, response) -> None:
        self._response = response

    def request(self, method: str, url: str, **kwargs):
        return self._response


def test_looks_like_directory_listing_markers() -> None:
    assert looks_like_directory_listing(APACHE_BODY) is True
    assert looks_like_directory_listing(NGINX_BODY) is True
    assert looks_like_directory_listing(
        "<html><body><h1>Index of /pub/</h1></body></html>") is True


def test_looks_like_directory_listing_rejects_prose_and_empty() -> None:
    # Words alone are not a listing: no <title>/<h1> "Index of /" marker.
    assert looks_like_directory_listing(
        "<html><body><p>See the index of /files/ in the docs.</p></body></html>") is False
    assert looks_like_directory_listing(
        "<html><head><title>Index of things</title></head></html>") is False
    assert looks_like_directory_listing("") is False
    assert looks_like_directory_listing(NORMAL_BODY) is False


def test_fetch_with_retry_flags_listing_only_when_inspecting() -> None:
    body = APACHE_BODY.encode("utf-8")
    outcome = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, body)), "https://example.com/files",
        max_retries=0, inspect_body=True))
    assert outcome.is_directory_listing is True
    outcome_no_inspect = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, body)), "https://example.com/files",
        max_retries=0))
    assert outcome_no_inspect.is_directory_listing is False
    outcome_normal = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponse(200, NORMAL_BODY.encode("utf-8"))),
        "https://example.com/", max_retries=0, inspect_body=True))
    assert outcome_normal.is_directory_listing is False


def test_fetch_with_retry_without_body_reader_fails_open() -> None:
    outcome = asyncio.run(fetch_with_retry(
        _FakeSession(_FakeResponseNoBody(200)), "https://example.com/x",
        max_retries=0, inspect_body=True))
    assert outcome.is_directory_listing is False


def test_listing_note_in_terminal_and_plain_output() -> None:
    flagged = ScanResult(path="/files", status_code=200, url="https://example.com/files",
                         reason="OK", size=512, is_directory_listing=True)
    assert "(directory listing)" in format_result(flagged)
    assert "(directory listing)" in plain_result_line(flagged)
    plain = ScanResult(path="/files", status_code=200, url="https://example.com/files",
                       reason="OK", size=512)
    assert "(directory listing)" not in plain_result_line(plain)


def test_scan_counts_directory_listings(monkeypatch) -> None:
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=512,
                            attempts=1, is_directory_listing=True)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["files"], threads=1, detect_wildcards=False))
    assert summary.hits == 1
    assert summary.directory_listings == 1
