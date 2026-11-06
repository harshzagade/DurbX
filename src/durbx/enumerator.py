from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
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
# Small built-in pool of common browser User-Agents for --random-agent.
# Round-robin rotation (not random choice) keeps scans reproducible and
# the rotation trivially testable; the pool is deliberately short so a
# scan's traffic still looks like ordinary browser traffic.
RANDOM_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
DEFAULT_METHOD = "GET"
VALID_METHODS = ("GET", "HEAD", "POST")
RETRY_BACKOFF_BASE = 1.0
MAX_RETRY_AFTER_SECONDS = 60.0
CHECKPOINT_VERSION = 1
DEFAULT_CHECKPOINT_EVERY = 10.0


@dataclass(frozen=True)
class ScanResult:
    path: str
    status_code: int | None
    url: str
    reason: str
    size: int
    attempts: int = 1
    is_directory_listing: bool = False
    redirect_target: str | None = None
    # Wall-clock time of the entry's request(s) in milliseconds, retries
    # included, measured inside scan(); None when no measurement was taken
    # (e.g. results built by hand in tests or older code paths).
    latency_ms: float | None = None
    # SHA-256 of the first 8 KB of a 200 body (None when the body was not
    # read — non-200s, HEAD responses, empty bodies). Rows sharing a hash
    # are collapsed into one representative row (see duplicate_count).
    body_hash: str | None = None
    # How many identical-body rows this representative stands for (1 when
    # nothing was collapsed into it). Finalized by the caller from
    # ScanSummary.duplicate_body_counts once the scan ends, since a
    # duplicate can arrive after the representative was already printed.
    duplicate_count: int = 1


@dataclass(frozen=True)
class ScanSummary:
    total: int
    completed: int
    hits: int
    wildcard_filtered: int = 0
    fingerprint: WildcardFingerprint | None = None
    directory_listings: int = 0
    # Hit counts per status code, e.g. {200: 3, 403: 1}. Only results
    # that pass the display filters count as hits, so wildcard-filtered
    # rows and failed requests (status None) never appear here.
    status_counts: dict[int, int] = field(default_factory=dict)
    # Rows hidden because their 200 body hashed identically to an
    # already-shown hit (template-duplicate pages the wildcard filter
    # cannot catch — same size is not required, same first-8KB hash is).
    duplicate_bodies_collapsed: int = 0
    # Body hash -> total rows collapsed into its representative (the
    # representative itself counts as 1), so durable outputs (-o, --json)
    # can carry the final per-row count.
    duplicate_body_counts: dict[str, int] = field(default_factory=dict)


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
    is_directory_listing: bool = False
    redirect_target: str | None = None
    body_hash: str | None = None


def hash_body_snippet(snippet: str) -> str | None:
    """SHA-256 hex of a response-body snippet, or ``None`` when empty.

    Empty snippets (HEAD responses, bodies without a reader, genuinely
    empty pages) hash to nothing — without this guard every HEAD 200
    would share one hash and collapse into a single row.
    """
    if not snippet:
        return None
    return hashlib.sha256(snippet.encode("utf-8")).hexdigest()


def normalize_target(target: str) -> str:
    candidate = target.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if not parsed.netloc:
        raise ValueError("Target must be a valid domain or URL.")

    normalized_path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path, "", "", ""))


def parse_wordlist_lines(lines) -> list[str]:
    """Normalize raw wordlist lines into candidate entries.

    Strips whitespace and leading slashes, skips blanks and ``#`` comments,
    and drops duplicates (first occurrence wins, order preserved). Shared
    by file and stdin loading so both sources behave identically.
    """
    entries: list[str] = []
    seen: set[str] = set()
    for raw_line in lines:
        entry = raw_line.strip().lstrip("/")
        if not entry or entry.startswith("#"):
            continue
        if entry not in seen:
            seen.add(entry)
            entries.append(entry)
    return entries


def _load_wordlist_file(source: Path) -> list[str]:
    if not source.is_file():
        raise FileNotFoundError(f"Wordlist not found: {source}")
    return parse_wordlist_lines(source.read_text(encoding="utf-8").splitlines())


def load_stdin_entries() -> list[str]:
    """Read candidate paths from stdin, one per line.

    Same normalization as wordlist files (blanks, ``#`` comments, duplicates
    dropped), so ``other-tool | durbx -u ... --stdin`` pipelines behave
    exactly like a wordlist file would.
    """
    return parse_wordlist_lines(sys.stdin.read().splitlines())


def load_wordlist(path: str) -> list[str]:
    if path == "-":
        return load_stdin_entries()
    sources = [Path(path).expanduser().resolve()]
    entries: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for entry in _load_wordlist_file(source):
            if entry not in seen:
                seen.add(entry)
                entries.append(entry)
    return entries


def load_targets(path: str) -> list[str]:
    """Read target URLs from a file, one per line.

    Blank lines and ``#`` comments are skipped. Each remaining line is
    normalized with ``normalize_target()`` (a missing scheme defaults to
    https). Duplicates are dropped, order preserved.

    Raises ``FileNotFoundError`` for a missing file and ``ValueError``
    (naming the offending line number) for a line that is not a valid
    target, so a typo fails fast instead of silently scanning junk.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Targets file not found: {source}")
    targets: list[str] = []
    seen: set[str] = set()
    for lineno, raw_line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            normalized = normalize_target(line)
        except ValueError as exc:
            raise ValueError(f"Invalid target on line {lineno}: {exc}") from exc
        if normalized not in seen:
            seen.add(normalized)
            targets.append(normalized)
    return targets


def write_checkpoint(
    path: str,
    *,
    target: str,
    entries: list[str],
    completed: list[str],
    finished: bool,
) -> None:
    """Write a resume checkpoint as JSON (via a temp file + rename, so an
    interrupted write never leaves a corrupt checkpoint behind).

    ``entries`` is the full expanded entry list (order preserved) and
    ``completed`` the subset already processed; ``finished`` marks a scan
    that ran to completion, which ``--resume`` refuses to re-run.
    """
    payload = {
        "tool": "durbx",
        "checkpoint_version": CHECKPOINT_VERSION,
        "target": target,
        "finished": finished,
        "entries": list(entries),
        "completed": list(completed),
    }
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_checkpoint(path: str) -> dict:
    """Read and validate a checkpoint written by ``write_checkpoint``.

    Raises ``FileNotFoundError`` for a missing file and ``ValueError`` for
    anything that is not a DurbX checkpoint of the supported version.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Checkpoint is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Checkpoint is not a JSON object")
    if payload.get("tool") != "durbx":
        raise ValueError("Checkpoint was not written by DurbX")
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise ValueError(
            f"Unsupported checkpoint version: {payload.get('checkpoint_version')!r}"
        )
    for key in ("target", "entries", "completed", "finished"):
        if key not in payload:
            raise ValueError(f"Checkpoint is missing {key!r}")
    return payload


def parse_status_codes(raw_value: str | None) -> list[int]:
    """Parse a comma-separated status-code list into ints.

    Single codes (``200``) and inclusive ranges (``200-299``) may be
    mixed, e.g. ``200,301,500-599``. Ranges expand in order and the
    result is deduplicated (first occurrence wins), so ``--status`` /
    ``--exclude`` membership checks stay simple. Malformed tokens,
    reversed ranges (``299-200``), and endpoints outside 100-599 fail
    fast with ``ValueError`` instead of silently matching nothing.
    """
    if not raw_value:
        return []
    codes: list[int] = []
    seen: set[int] = set()

    def _add(code: int) -> None:
        if code not in seen:
            seen.add(code)
            codes.append(code)

    for chunk in raw_value.split(","):
        value = chunk.strip()
        if not value:
            continue
        if "-" in value:
            parts = [part.strip() for part in value.split("-")]
            if len(parts) != 2:
                raise ValueError(f"Invalid status code range: {value}")
            try:
                low, high = int(parts[0]), int(parts[1])
            except ValueError as exc:
                raise ValueError(f"Invalid status code range: {value}") from exc
            if low > high or low < 100 or high > 599:
                raise ValueError(f"Invalid status code range: {value}")
            for code in range(low, high + 1):
                _add(code)
            continue
        try:
            _add(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid status code: {value}") from exc
    return codes


def parse_match_lengths(raw_value: str | None) -> list[int]:
    """Parse a comma-separated list of body sizes for ``--match-length``.

    Same validation as ``parse_filter_lengths`` (non-integer or negative
    values fail fast) — the two flags share a size-list grammar, only the
    polarity differs: match-length is an allowlist, filter-length a denylist.
    """
    return parse_filter_lengths(raw_value)


def parse_filter_lengths(raw_value: str | None) -> list[int]:
    """Parse a comma-separated list of response body sizes into ints.

    Raises ``ValueError`` for non-integer tokens or negative values — a
    negative size can never match, so it is almost certainly a typo.
    """
    if not raw_value:
        return []
    sizes: list[int] = []
    for chunk in raw_value.split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            size = int(value)
        except ValueError as exc:
            raise ValueError(f"Invalid body size: {value}") from exc
        if size < 0:
            raise ValueError(f"Invalid body size (must be >= 0): {value}")
        sizes.append(size)
    return sizes


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

    Both forms from RFC 9110 are honored: delta-seconds, and an HTTP-date
    (converted to "seconds from now"; a date already in the past means
    retry immediately, 0.0). The result is clamped to
    ``MAX_RETRY_AFTER_SECONDS`` so a hostile or misconfigured server
    cannot stall the scan. Returns ``None`` when the header is absent,
    empty, negative, or unparseable.
    """
    if raw_value is None:
        return None
    value_text = raw_value.strip()
    if not value_text:
        return None
    try:
        seconds = float(value_text)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds < 0:
            return None
        return min(seconds, MAX_RETRY_AFTER_SECONDS)
    try:
        retry_at = parsedate_to_datetime(value_text)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        # A bare HTTP-date has no zone; RFC 9110 dates are GMT.
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    delta = (retry_at - datetime.now(timezone.utc)).total_seconds()
    if delta <= 0:
        return 0.0
    return min(delta, MAX_RETRY_AFTER_SECONDS)


def retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Seconds to wait before retry number ``attempt`` (0-based).

    Defaults to exponential backoff (1s, 2s, 4s, ...); a parsed
    ``Retry-After`` value overrides the computed delay.
    """
    if retry_after is not None:
        return retry_after
    return RETRY_BACKOFF_BASE * (2 ** max(0, attempt))


def parse_rate_limit(raw_value: float | None) -> float | None:
    """Validate a ``--rate-limit`` value (requests per second).

    ``None`` disables throttling. A non-positive rate can never pace a
    scan, so it fails fast instead of silently meaning "unlimited".
    """
    if raw_value is None:
        return None
    rate = float(raw_value)
    if rate <= 0:
        raise ValueError("--rate-limit must be > 0")
    return rate


class UserAgentRotator:
    """Round-robin User-Agent rotation for ``--random-agent``.

    ``next()`` returns the next browser User-Agent from
    :data:`RANDOM_USER_AGENTS`, wrapping to the start of the pool. One
    rotator is shared by all scan workers, so concurrent requests still
    cycle through the pool instead of every worker pinning one agent.
    """

    def __init__(self, user_agents: tuple[str, ...] = RANDOM_USER_AGENTS) -> None:
        if not user_agents:
            raise ValueError("User-Agent pool must not be empty")
        self._user_agents = tuple(user_agents)
        self._index = 0

    def next(self) -> str:
        agent = self._user_agents[self._index % len(self._user_agents)]
        self._index += 1
        return agent


class RateLimiter:
    """Async token bucket shared across all scan workers.

    The bucket holds up to one second's worth of tokens (at least one),
    refills continuously at ``rate_per_second``, and each request spends
    one token. When the bucket is empty, ``acquire()`` sleeps until a
    token is available. Unlike the per-worker ``--delay`` pause, this
    caps the *global* request rate, which is what strict server-side
    rate limits actually enforce. The lock is held while waiting so
    concurrent workers cannot all slip through on the same token.

    ``clock``/``sleep`` are injectable for tests; both default to the
    real ``time.monotonic``/``asyncio.sleep`` at call time.
    """

    def __init__(
        self,
        rate_per_second: float,
        *,
        clock=None,
        sleep=None,
    ) -> None:
        rate = float(rate_per_second)
        if rate <= 0:
            raise ValueError("--rate-limit must be > 0")
        self.rate = rate
        self.capacity = max(1.0, rate)
        self._tokens = self.capacity
        self._last: float | None = None
        self._lock = asyncio.Lock()
        self._clock = clock
        self._sleep = sleep

    def _now(self) -> float:
        return (self._clock or time.monotonic)()

    async def _do_sleep(self, seconds: float) -> None:
        await (self._sleep or asyncio.sleep)(seconds)

    async def acquire(self) -> None:
        async with self._lock:
            now = self._now()
            if self._last is None:
                self._last = now
            else:
                refill = max(0.0, now - self._last) * self.rate
                self._tokens = min(self.capacity, self._tokens + refill)
                self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self.rate
            await self._do_sleep(wait)
            # The wait just bought exactly one token, which this
            # acquisition spends; the clock is re-read so a real clock
            # and a frozen test clock both stay consistent.
            self._tokens = 0.0
            self._last = self._now()


async def fetch_with_retry(
    session,
    url: str,
    *,
    method: str = DEFAULT_METHOD,
    max_retries: int,
    allow_redirects: bool = False,
    proxy: str | None = None,
    inspect_body: bool = False,
    headers: dict[str, str] | None = None,
) -> FetchOutcome:
    """Request ``url`` with ``method``, backing off and retrying on HTTP 429.

    Retries up to ``max_retries`` times after the first attempt (0 disables
    retrying). Waits out the server's ``Retry-After`` header when present,
    otherwise uses exponential backoff. Non-429 responses are returned
    immediately. ``aiohttp`` client errors and timeouts propagate to the
    caller. When ``inspect_body`` is set, a 200 response's first 8 KB are
    read once and used for both checks derived from it: server autoindex
    markers (see :func:`looks_like_directory_listing`) and the SHA-256
    body hash used for duplicate-body dedupe (see
    :func:`hash_body_snippet`); the wildcard probe leaves it off since it
    only needs status + size. A 3xx response's ``Location``
    header is captured as ``redirect_target`` so hit output can show
    where the redirect points instead of repeating the requested URL.
    """
    retries = max(0, max_retries)
    attempt = 0
    while True:
        request_kwargs: dict = {"allow_redirects": allow_redirects, "proxy": proxy}
        if headers is not None:
            # Per-request headers override the session-level headers in
            # aiohttp, which is how --random-agent rotates the User-Agent
            # without rebuilding the session per request.
            request_kwargs["headers"] = headers
        async with session.request(method, url, **request_kwargs) as response:
            status = response.status
            if status != 429 or attempt >= retries:
                listing = False
                body_hash = None
                if inspect_body and status == 200:
                    # One read serves both body-derived checks; the hash
                    # covers the same first-8KB window, so bodies that
                    # differ only past 8 KB still collapse (documented).
                    snippet = await _read_body_snippet(response)
                    listing = looks_like_directory_listing(snippet)
                    body_hash = hash_body_snippet(snippet)
                # The Location header is the redirect's real destination:
                # without it, a 3xx hit's "-> url" suffix just repeats the
                # URL that was requested. Only 3xx responses carry one;
                # a Location on any other status is ignored.
                redirect_target = None
                if 300 <= status < 400:
                    redirect_target = response.headers.get("Location") or None
                return FetchOutcome(
                    status=status,
                    reason=response.reason or "OK",
                    content_length=int(response.headers.get("Content-Length", "0") or 0),
                    attempts=attempt + 1,
                    is_directory_listing=listing,
                    redirect_target=redirect_target,
                    body_hash=body_hash,
                )
            delay = retry_delay(attempt, parse_retry_after(response.headers.get("Retry-After")))
            await asyncio.sleep(delay)
            attempt += 1


_BODY_SNIPPET_LIMIT = 8192

_DIRECTORY_LISTING_PATTERNS = (
    # Apache / nginx / lighttpd autoindex pages title (and head) their
    # listings "Index of /path/". Requiring the title/h1 form (not just
    # the words anywhere in the body) keeps ordinary pages that merely
    # mention an index from being flagged.
    re.compile(r"<title>\s*index of\s+/", re.IGNORECASE),
    re.compile(r"<h1[^>]*>\s*index of\s+/", re.IGNORECASE),
)


def looks_like_directory_listing(body_text: str) -> bool:
    """True when a response body looks like a server autoindex page.

    Matches the ``<title>Index of /...`` / ``<h1>Index of /...`` markers
    used by Apache, nginx, and lighttpd directory listings. A page that
    only mentions "Index of" in prose does not match.
    """
    if not body_text:
        return False
    return any(pattern.search(body_text) for pattern in _DIRECTORY_LISTING_PATTERNS)


async def _read_body_snippet(response) -> str:
    """Read up to 8 KB of a response body as text, best-effort.

    Real aiohttp responses expose ``.content.read(n)``; test doubles and
    stubs may expose no body reader at all — in that case (or on any
    read error) returns ``""`` so detection fails open instead of
    breaking the scan.
    """
    content = getattr(response, "content", None)
    read = getattr(content, "read", None)
    if not callable(read):
        return ""
    try:
        chunk = await read(_BODY_SNIPPET_LIMIT)
    except Exception:
        return ""
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="ignore")
    return str(chunk)


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
    filter_lengths: list[int] | None = None,
    match_lengths: list[int] | None = None,
) -> bool:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    filter_lengths = filter_lengths or []
    match_lengths = match_lengths or []
    if result.status_code is None:
        return False
    if status_filter and result.status_code not in status_filter:
        return False
    if exclude_filter and result.status_code in exclude_filter:
        return False
    # --filter-length (gobuster-style): hide responses whose body size matches
    # one of the given sizes. Checked before the --all default rule so an
    # explicit user filter always wins.
    if filter_lengths and result.size in filter_lengths:
        return False
    # --match-length (inverse of --filter-length): when given, show ONLY
    # responses whose body size is in the list, so a known interesting size
    # can be zeroed in on. Also checked before the --all default rule, and
    # combined (AND) with the status filters above.
    if match_lengths and result.size not in match_lengths:
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
    filter_lengths: list[int] | None = None,
    match_lengths: list[int] | None = None,
    checkpoint_file: str | None = None,
    checkpoint_every: float = DEFAULT_CHECKPOINT_EVERY,
    resume_completed: list[str] | None = None,
    rate_limit: float | None = None,
    random_agent: bool = False,
) -> ScanSummary:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    filter_lengths = filter_lengths or []
    match_lengths = match_lengths or []
    entries = expand_extensions(entries, extensions or [])
    total = len(entries) + len(resume_completed or [])
    completed = 0
    hits = 0
    wildcard_filtered = 0
    directory_listings = 0
    status_counts: dict[int, int] = {}
    # Body hashes of already-shown 200 hits -> rows collapsed into each
    # (representative included). Only displayed hits seed the map, so a
    # row the wildcard or display filters hid never blocks a later row.
    body_hash_counts: dict[str, int] = {}
    duplicate_bodies_collapsed = 0
    fingerprint: WildcardFingerprint | None = None
    start_time = time.time()
    last_render_time = 0.0
    print_lock = asyncio.Lock()
    client_timeout = aiohttp.ClientTimeout(total=max(timeout, 0.1))
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    # Entries finished in a previous (interrupted) run, carried over so the
    # checkpoint keeps the full picture and stats count the whole scan.
    completed_entries: list[str] = list(resume_completed or [])
    last_checkpoint_write = 0.0
    checkpoint_warned = False

    def _write_checkpoint(finished: bool) -> None:
        """Persist scan progress; a failed write warns once, never kills
        the scan — the in-memory scan state is unaffected."""
        nonlocal last_checkpoint_write, checkpoint_warned
        if not checkpoint_file:
            return
        try:
            write_checkpoint(
                checkpoint_file,
                target=base_url,
                entries=entries,
                completed=completed_entries,
                finished=finished,
            )
        except OSError as exc:
            if not checkpoint_warned:
                checkpoint_warned = True
                print(f"\n[!] Could not write checkpoint {checkpoint_file}: {exc}")
            return
        last_checkpoint_write = time.time()

    def _maybe_checkpoint() -> None:
        if checkpoint_file and time.time() - last_checkpoint_write >= checkpoint_every:
            _write_checkpoint(finished=False)

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

    # --random-agent rotates the User-Agent per scan request, overriding
    # --user-agent — but an explicit -H User-Agent header still wins,
    # matching the existing -H-over---user-agent precedence.
    explicit_agent = any(
        name.lower() == "user-agent" for name in (custom_headers or {})
    )
    rotator = UserAgentRotator() if (random_agent and not explicit_agent) else None

    async def scan(session: aiohttp.ClientSession, entry: str) -> ScanResult:
        nonlocal completed, hits, wildcard_filtered, directory_listings, duplicate_bodies_collapsed
        encoded_entry = quote(entry, safe="/")
        target_url = f"{base_url}/{encoded_entry}"
        request_headers = (
            {"User-Agent": rotator.next()} if rotator is not None else None
        )
        # Wall-clock latency of this entry's request, retries and their
        # backoff included: that is the time the entry actually cost the
        # scan, which is what the summary's slowest-hit list should rank.
        started = time.monotonic()
        try:
            outcome = await fetch_with_retry(
                session,
                target_url,
                method=method,
                max_retries=max_retries,
                allow_redirects=follow_redirects,
                proxy=proxy,
                inspect_body=True,
                headers=request_headers,
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
                latency_ms=(time.monotonic() - started) * 1000,
            )
        else:
            result = ScanResult(
                path=f"/{entry}",
                status_code=outcome.status,
                url=target_url,
                reason=outcome.reason,
                size=outcome.content_length,
                attempts=outcome.attempts,
                is_directory_listing=outcome.is_directory_listing,
                redirect_target=outcome.redirect_target,
                latency_ms=(time.monotonic() - started) * 1000,
                body_hash=outcome.body_hash,
            )

        async with print_lock:
            completed += 1
            # Track per-entry progress for checkpoints (completion order may
            # differ from queue order with multiple workers; the set is what
            # matters for resume).
            completed_entries.append(entry)
            _maybe_checkpoint()
            if is_wildcard_match(result, fingerprint):
                # Soft-404 noise: same status + body size as the probe of a
                # random nonexistent path. Hidden, but counted separately so
                # the user can see the filter did something.
                wildcard_filtered += 1
            elif should_show_result(result, status_filter=status_filter, exclude_filter=exclude_filter, all_codes=all_codes, filter_lengths=filter_lengths, match_lengths=match_lengths):
                if (
                    result.status_code == 200
                    and result.body_hash is not None
                    and result.body_hash in body_hash_counts
                ):
                    # Template-duplicate page: its first 8 KB hash matches
                    # an already-shown hit, so it collapses into that
                    # representative row instead of printing another line.
                    # The representative's count is finalized from
                    # body_hash_counts after the scan (see cli.py).
                    duplicate_bodies_collapsed += 1
                    body_hash_counts[result.body_hash] += 1
                else:
                    if result.status_code == 200 and result.body_hash is not None:
                        body_hash_counts[result.body_hash] = 1
                    hits += 1
                    if result.status_code is not None:
                        status_counts[result.status_code] = (
                            status_counts.get(result.status_code, 0) + 1
                        )
                    if result.is_directory_listing:
                        directory_listings += 1
                    hit = True
                    print("\r" + " " * 100 + "\r", end="")
                    if on_result is not None:
                        on_result(result)
                    else:
                        print(f"{result.path} {result.status_code}")
            render_progress(force=completed == total)
        return result

    limiter = RateLimiter(rate_limit) if rate_limit is not None else None

    async def worker(session: aiohttp.ClientSession) -> None:
        while True:
            entry = await queue.get()
            if entry is None:
                queue.task_done()
                break
            try:
                if limiter is not None:
                    # Global throttle: one token per request, shared by
                    # every worker, on top of the per-worker --delay.
                    await limiter.acquire()
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
        _write_checkpoint(finished=False)
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
        _write_checkpoint(finished=True)

    print()
    return ScanSummary(
        total=total,
        completed=completed + len(resume_completed or []),
        hits=hits,
        wildcard_filtered=wildcard_filtered,
        fingerprint=fingerprint,
        directory_listings=directory_listings,
        status_counts=status_counts,
        duplicate_bodies_collapsed=duplicate_bodies_collapsed,
        duplicate_body_counts=body_hash_counts,
    )
