from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
import secrets
import time
from typing import Callable
from urllib.parse import quote
from urllib.parse import urlparse, urlunparse

import aiohttp


DEFAULT_TIMEOUT = 3.0
DEFAULT_THREADS = 50
DEFAULT_MAX_RETRIES = 3
DEFAULT_DELAY = 0.0
DEFAULT_USER_AGENT = "DurbX/0.1"
DEFAULT_METHOD = "GET"
VALID_METHODS = ("GET", "HEAD", "POST")
RETRY_BACKOFF_BASE = 1.0
MAX_RETRY_AFTER_SECONDS = 60.0


@dataclass(frozen=True)
class ScanResult:
    path: str
    status_code: int | None
    url: str
    reason: str
    size: int


@dataclass(frozen=True)
class ScanSummary:
    total: int
    completed: int
    hits: int
    wildcard_filtered: int = 0
    fingerprint: WildcardFingerprint | None = None


@dataclass(frozen=True)
class WildcardFingerprint:
    """Soft-404 fingerprint: the (status, body size) a random nonexistent
    path returns on this target. Scan results indistinguishable from it are
    treated as wildcard noise and hidden."""

    status: int
    size: int


@dataclass(frozen=True)
class FetchOutcome:
    status: int
    reason: str
    content_length: int
    attempts: int


def normalize_target(target: str) -> str:
    candidate = target.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if not parsed.netloc:
        raise ValueError("Target must be a valid domain or URL.")

    normalized_path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def _load_wordlist_file(source: Path) -> list[str]:
    if not source.is_file():
        raise FileNotFoundError(f"Wordlist not found: {source}")

    entries: list[str] = []
    seen: set[str] = set()
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        entry = raw_line.strip().lstrip("/")
        if not entry or entry.startswith("#"):
            continue
        if entry not in seen:
            seen.add(entry)
            entries.append(entry)
    return entries


def load_wordlist(path: str) -> list[str]:
    sources = [Path(path).expanduser().resolve()]
    entries: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for entry in _load_wordlist_file(source):
            if entry not in seen:
                seen.add(entry)
                entries.append(entry)
    return entries


def parse_status_codes(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []
    codes: list[int] = []
    for chunk in raw_value.split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            codes.append(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid status code: {value}") from exc
    return codes


_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def parse_method(raw_value: str | None) -> str:
    """Normalize the ``-m/--method`` value to an uppercase HTTP method.

    Defaults to ``GET``. Raises ``ValueError`` for anything outside
    GET/HEAD/POST — the only verbs that make sense for directory probing
    (other verbs would turn the tool into a generic method tester).
    """
    method = (raw_value or DEFAULT_METHOD).strip().upper()
    if method not in VALID_METHODS:
        raise ValueError(
            f"Invalid HTTP method: {raw_value!r} (choose from {', '.join(VALID_METHODS)})"
        )
    return method


def parse_headers(raw_values: list[str] | None) -> dict[str, str]:
    """Parse repeatable ``-H/--header "Name: value"`` flags into a dict.

    Splits each item on the first colon (values may contain colons).
    Raises ``ValueError`` when an item has no colon, an empty name, or a
    name that is not a valid HTTP token (RFC 9110), so malformed headers
    fail fast instead of blowing up mid-scan. Later duplicates overwrite
    earlier ones.
    """
    headers: dict[str, str] = {}
    for item in raw_values or []:
        name, separator, value = item.partition(":")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"Invalid header (expected 'Name: value'): {item!r}")
        if not _HEADER_NAME_RE.match(name):
            raise ValueError(f"Invalid header name: {name!r}")
        headers[name] = value.strip()
    return headers


def parse_extensions(raw_value: str | None) -> list[str]:
    """Parse a comma-separated extension list into ``['.ext', ...]``.

    Accepts tokens with or without a leading dot (``php`` or ``.php``).
    Raises ``ValueError`` for empty tokens or tokens containing ``/`` or
    whitespace, which would produce nonsense request paths.
    """
    if not raw_value:
        return []
    extensions: list[str] = []
    for chunk in raw_value.split(","):
        token = chunk.strip()
        if not token:
            raise ValueError("Invalid file extension: empty token")
        token = "." + token.lstrip(".")
        if "/" in token or any(char.isspace() for char in token):
            raise ValueError(f"Invalid file extension: {chunk.strip()!r}")
        if token not in extensions:
            extensions.append(token)
    return extensions


def expand_extensions(entries: list[str], extensions: list[str]) -> list[str]:
    """Expand a wordlist with per-extension variants, gobuster-style.

    For each entry, keeps the bare entry first, then one ``entry + ext``
    variant per extension. Entries ending in ``/`` (directory guesses) are
    not given extension variants. Duplicates are dropped, order preserved.
    """
    if not extensions:
        return list(entries)
    expanded: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        variants = [entry]
        if not entry.endswith("/"):
            variants.extend(entry + ext for ext in extensions)
        for variant in variants:
            if variant not in seen:
                seen.add(variant)
                expanded.append(variant)
    return expanded


def parse_retry_after(raw_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value into seconds.

    Only the delta-seconds form is honored; the HTTP-date form is ignored.
    The result is clamped to ``MAX_RETRY_AFTER_SECONDS`` so a hostile or
    misconfigured server cannot stall the scan. Returns ``None`` when the
    header is absent, empty, negative, or unparseable.
    """
    if raw_value is None:
        return None
    value_text = raw_value.strip()
    if not value_text:
        return None
    try:
        seconds = float(value_text)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Seconds to wait before retry number ``attempt`` (0-based).

    Defaults to exponential backoff (1s, 2s, 4s, ...); a parsed
    ``Retry-After`` value overrides the computed delay.
    """
    if retry_after is not None:
        return retry_after
    return RETRY_BACKOFF_BASE * (2 ** max(0, attempt))


async def fetch_with_retry(
    session,
    url: str,
    *,
    method: str = DEFAULT_METHOD,
    max_retries: int,
    allow_redirects: bool = False,
    proxy: str | None = None,
) -> FetchOutcome:
    """Request ``url`` with ``method``, backing off and retrying on HTTP 429.

    Retries up to ``max_retries`` times after the first attempt (0 disables
    retrying). Waits out the server's ``Retry-After`` header when present,
    otherwise uses exponential backoff. Non-429 responses are returned
    immediately. ``aiohttp`` client errors and timeouts propagate to the
    caller.
    """
    retries = max(0, max_retries)
    attempt = 0
    while True:
        async with session.request(method, url, allow_redirects=allow_redirects, proxy=proxy) as response:
            status = response.status
            if status != 429 or attempt >= retries:
                return FetchOutcome(
                    status=status,
                    reason=response.reason or "OK",
                    content_length=int(response.headers.get("Content-Length", "0") or 0),
                    attempts=attempt + 1,
                )
            delay = retry_delay(attempt, parse_retry_after(response.headers.get("Retry-After")))
            await asyncio.sleep(delay)
            attempt += 1


def wildcard_probe_path() -> str:
    """Random, near-unguessable path used for the soft-404 probe."""
    return f"durbx-wildcard-{secrets.token_hex(16)}"


async def detect_wildcard(
    session,
    base_url: str,
    *,
    method: str = DEFAULT_METHOD,
    max_retries: int,
    allow_redirects: bool = False,
    proxy: str | None = None,
) -> WildcardFingerprint | None:
    """Probe a random nonexistent path to fingerprint soft-404 behavior.

    Returns a fingerprint when the probe gets anything other than 404
    (the server answers unknown paths with content, e.g. a catch-all
    page or a redirect to one). Returns ``None`` when the probe 404s
    (no wildcard behavior) or when the probe itself fails — fail open,
    never filter on a guess. Uses the same method and redirect policy as
    the scan so the fingerprint matches what the scan will actually see.
    """
    probe_url = f"{base_url}/{wildcard_probe_path()}"
    try:
        outcome = await fetch_with_retry(
            session,
            probe_url,
            method=method,
            max_retries=max_retries,
            allow_redirects=allow_redirects,
            proxy=proxy,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None
    if outcome.status == 404:
        return None
    return WildcardFingerprint(status=outcome.status, size=outcome.content_length)


def is_wildcard_match(
    result: ScanResult,
    fingerprint: WildcardFingerprint | None,
) -> bool:
    """True when a result is indistinguishable from the soft-404 probe."""
    return (
        fingerprint is not None
        and result.status_code == fingerprint.status
        and result.size == fingerprint.size
    )


def should_show_result(
    result: ScanResult,
    status_filter: list[int] | None = None,
    exclude_filter: list[int] | None = None,
    all_codes: bool = False,
) -> bool:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    if result.status_code is None:
        return False
    if status_filter and result.status_code not in status_filter:
        return False
    if exclude_filter and result.status_code in exclude_filter:
        return False
    # If all_codes flag is set, show everything except 404
    if all_codes:
        return result.status_code != 404
    # Otherwise, only show specified codes or default to 200
    if not status_filter and result.status_code != 200:
        return False
    return True


async def enumerate_directories(
    base_url: str,
    entries: list[str],
    timeout: float = DEFAULT_TIMEOUT,
    threads: int = DEFAULT_THREADS,
    status_filter: list[int] | None = None,
    exclude_filter: list[int] | None = None,
    all_codes: bool = False,
    proxy: str | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    extensions: list[str] | None = None,
    on_result: Callable[[ScanResult], None] | None = None,
    delay: float = DEFAULT_DELAY,
    user_agent: str = DEFAULT_USER_AGENT,
    method: str = DEFAULT_METHOD,
    follow_redirects: bool = False,
    detect_wildcards: bool = True,
    custom_headers: dict[str, str] | None = None,
) -> ScanSummary:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    entries = expand_extensions(entries, extensions or [])
    total = len(entries)
    completed = 0
    hits = 0
    wildcard_filtered = 0
    fingerprint: WildcardFingerprint | None = None
    start_time = time.time()
    last_render_time = 0.0
    print_lock = asyncio.Lock()
    client_timeout = aiohttp.ClientTimeout(total=max(timeout, 0.1))
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def render_progress(force: bool = False) -> None:
        nonlocal last_render_time
        now = time.time()
        if not force and (now - last_render_time) < 0.1:
            return
        last_render_time = now
        percent = (completed / total) if total else 0.0
        bar_len = 20
        filled = int(bar_len * percent)
        bar = "█" * filled + "░" * (bar_len - filled)
        elapsed = time.time() - start_time
        rate = completed / elapsed if elapsed > 0 else 0.0
        remaining = (total - completed) / rate if rate > 0 else 0.0
        eta = time.strftime("%M:%S", time.gmtime(remaining))
        print(f"\r[{bar}] {percent * 100:4.1f}% ({completed}/{total}) | ETA: {eta}", end="", flush=True)

    async def scan(session: aiohttp.ClientSession, entry: str) -> ScanResult:
        nonlocal completed, hits, wildcard_filtered
        encoded_entry = quote(entry, safe="/")
        target_url = f"{base_url}/{encoded_entry}"
        try:
            outcome = await fetch_with_retry(
                session,
                target_url,
                method=method,
                max_retries=max_retries,
                allow_redirects=follow_redirects,
                proxy=proxy,
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            detail = str(exc).strip()
            if not detail:
                detail = "Request timed out" if isinstance(exc, asyncio.TimeoutError) else "Request failed"
            result = ScanResult(
                path=f"/{entry}",
                status_code=None,
                url=target_url,
                reason=detail,
                size=0,
            )
        else:
            result = ScanResult(
                path=f"/{entry}",
                status_code=outcome.status,
                url=target_url,
                reason=outcome.reason,
                size=outcome.content_length,
            )

        async with print_lock:
            completed += 1
            if is_wildcard_match(result, fingerprint):
                # Soft-404 noise: same status + body size as the probe of a
                # random nonexistent path. Hidden, but counted separately so
                # the user can see the filter did something.
                wildcard_filtered += 1
            elif should_show_result(result, status_filter=status_filter, exclude_filter=exclude_filter, all_codes=all_codes):
                hits += 1
                hit = True
                print("\r" + " " * 100 + "\r", end="")
                if on_result is not None:
                    on_result(result)
                else:
                    print(f"{result.path} {result.status_code}")
            render_progress(force=completed == total)
        return result

    async def worker(session: aiohttp.ClientSession) -> None:
        while True:
            entry = await queue.get()
            if entry is None:
                queue.task_done()
                break
            try:
                await scan(session, entry)
                if delay > 0:
                    # Per-worker pause between requests: keeps request timing
                    # human-like for stealthy scans and rate-limited targets.
                    await asyncio.sleep(delay)
            finally:
                queue.task_done()

    connector = aiohttp.TCPConnector(
        limit=max(1, threads),
        limit_per_host=max(1, threads),
        ttl_dns_cache=300,
        ssl=False,
    )
    # Custom -H headers take precedence over --user-agent (curl parity).
    request_headers = {"User-Agent": user_agent}
    request_headers.update(custom_headers or {})
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=client_timeout,
        headers=request_headers,
    ) as session:
        if detect_wildcards:
            fingerprint = await detect_wildcard(
                session,
                base_url,
                method=method,
                max_retries=max_retries,
                allow_redirects=follow_redirects,
                proxy=proxy,
            )
            if fingerprint is not None:
                print(
                    f"[i] Wildcard filter active: hiding responses matching "
                    f"{fingerprint.status} ({fingerprint.size}B)"
                )
        worker_count = max(1, threads)
        for entry in entries:
            queue.put_nowait(entry)
        for _ in range(worker_count):
            queue.put_nowait(None)

        tasks = [asyncio.create_task(worker(session)) for _ in range(worker_count)]
        try:
            await queue.join()
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    print()
    return ScanSummary(
        total=total,
        completed=completed,
        hits=hits,
        wildcard_filtered=wildcard_filtered,
        fingerprint=fingerprint,
    )
