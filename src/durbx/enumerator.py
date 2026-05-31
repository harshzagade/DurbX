from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable
from urllib.parse import quote
from urllib.parse import urlparse, urlunparse

import aiohttp


DEFAULT_TIMEOUT = 3.0
DEFAULT_THREADS = 50


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


def should_show_result(
    result: ScanResult,
    status_filter: list[int] | None = None,
    exclude_filter: list[int] | None = None,
) -> bool:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    if result.status_code is None:
        return False
    if status_filter and result.status_code not in status_filter:
        return False
    if exclude_filter and result.status_code in exclude_filter:
        return False
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
    on_result: Callable[[ScanResult], None] | None = None,
) -> ScanSummary:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    total = len(entries)
    completed = 0
    hits = 0
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
        nonlocal completed, hits
        encoded_entry = quote(entry, safe="/")
        target_url = f"{base_url}/{encoded_entry}"
        try:
            async with session.get(
                target_url,
                allow_redirects=False,
                proxy=proxy,
            ) as response:
                result = ScanResult(
                    path=f"/{entry}",
                    status_code=response.status,
                    url=target_url,
                    reason=response.reason or "OK",
                    size=int(response.headers.get("Content-Length", "0") or 0),
                )
        except aiohttp.ClientError as exc:
            result = ScanResult(
                path=f"/{entry}",
                status_code=None,
                url=target_url,
                reason=str(exc),
                size=0,
            )
        except asyncio.TimeoutError:
            result = ScanResult(
                path=f"/{entry}",
                status_code=None,
                url=target_url,
                reason="Request timed out",
                size=0,
            )

        async with print_lock:
            completed += 1
            if should_show_result(result, status_filter=status_filter, exclude_filter=exclude_filter, all_codes=all_codes):
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
            finally:
                queue.task_done()

    connector = aiohttp.TCPConnector(
        limit=max(1, threads),
        limit_per_host=max(1, threads),
        ttl_dns_cache=300,
        ssl=False,
    )
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=client_timeout,
        headers={"User-Agent": "DurbX/0.1"},
    ) as session:
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
    return ScanSummary(total=total, completed=completed, hits=hits)
