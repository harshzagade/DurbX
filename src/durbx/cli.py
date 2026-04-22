from __future__ import annotations

import argparse
import asyncio
import sys

from .enumerator import (
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT,
    enumerate_directories,
    load_wordlist,
    normalize_target,
    parse_status_codes,
)
from .formatter import format_result


def show_banner() -> None:
    print(
        """
==================== DurbX ====================
      Directory Enumeration Tool
==============================================
""".strip("\n")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="durbx",
        description="DurbX - Directory Enumeration Tool",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-u", "--url", required=True, help="Target URL")
    parser.add_argument("-w", "--wordlist", required=True, help="Wordlist file to use")
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS, help=f"Threads (default: {DEFAULT_THREADS})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--status", help="Show only these codes (e.g. 200,403)")
    parser.add_argument("--exclude", help="Exclude codes (e.g. 404,500)")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:8080)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    show_banner()

    try:
        base_url = normalize_target(args.url)
        entries = load_wordlist(args.wordlist)
        status_filter = parse_status_codes(args.status)
        exclude_filter = parse_status_codes(args.exclude)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
        return 2

    if not entries:
        parser.error("No wordlist entries were loaded.")
        return 2

    print(f"[+] URL        : {base_url}")
    print(f"[+] Wordlist   : {args.wordlist}")
    print(f"[+] Threads    : {max(args.threads, 1)}")
    print(f"[+] Total      : {len(entries)}")
    if args.proxy:
        print(f"[+] Proxy      : {args.proxy}")
    print("=" * 60)

    try:
        summary = asyncio.run(
            enumerate_directories(
                base_url=base_url,
                entries=entries,
                timeout=max(args.timeout, 0.1),
                threads=max(args.threads, 1),
                status_filter=status_filter,
                exclude_filter=exclude_filter,
                proxy=args.proxy,
                on_result=lambda result: print(format_result(result)),
            )
        )
    except KeyboardInterrupt:
        print()
        print("=" * 60)
        print("Scan interrupted by user")
        print("=" * 60)
        return 130

    print("=" * 60)
    print(f"Hits: {summary.hits}")
    print(f"Progress: {summary.completed} / {summary.total} (100.00%)")
    print("=" * 60)
    print("Finished")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
