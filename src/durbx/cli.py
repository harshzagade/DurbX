import argparse
import asyncio
import sys
import time
from .enumerator import (
    DEFAULT_DELAY,
    DEFAULT_MAX_RETRIES,
    DEFAULT_METHOD,
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    enumerate_directories,
    load_wordlist,
    normalize_target,
    parse_extensions,
    parse_headers,
    parse_method,
    parse_status_codes,
)
from .formatter import format_result, render_plain_results
from .utils import LOGO, setup_logging, console, print_help


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="durbx",
        description="DurbX - Directory Enumeration Tool",
        add_help=False
    )
    parser.add_argument("-u", "--url", required=True, help="Target URL")
    parser.add_argument("-w", "--wordlist", required=True, help="Wordlist file to use")
    parser.add_argument("-x", "--extensions", help="Append file extensions to each word (e.g. php,html)")
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS, help=f"Threads (default: {DEFAULT_THREADS})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES, help=f"Retries on HTTP 429 with backoff (default: {DEFAULT_MAX_RETRIES}; 0 disables)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Pause in seconds between requests per worker (default: {DEFAULT_DELAY}; for stealthy/rate-limited targets)")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help=f"Custom User-Agent header (default: {DEFAULT_USER_AGENT})")
    parser.add_argument("-H", "--header", action="append", default=None, help="Custom HTTP header, e.g. -H 'Authorization: Bearer abc' (repeatable; overrides --user-agent)")
    parser.add_argument("-m", "--method", default=DEFAULT_METHOD, help=f"HTTP method for requests (default: {DEFAULT_METHOD}; GET/HEAD/POST)")
    parser.add_argument("--follow-redirects", action="store_true", help="Follow 3xx redirects instead of reporting them (default: no)")
    parser.add_argument("--status", help="Show only these codes (e.g. 200,403)")
    parser.add_argument("--exclude", help="Exclude codes (e.g. 404,500)")
    parser.add_argument("-a", "--all", action="store_true", help="Show all status codes (except 404)")
    parser.add_argument("--no-wildcard", action="store_true", help="Disable soft-404 wildcard detection")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:8080)")
    parser.add_argument("-o", "--output", help="Save discovered hits to a file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Minimal output mode")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    
    # Check for help early to skip required validation
    if "-h" in sys.argv or "--help" in sys.argv:
        print_help()
        return 0

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # If parse fails (missing args), but help wasn't requested, 
        # let argparse handle the error message.
        return 2
    
    log = setup_logging(args.verbose, args.quiet)

    if not args.quiet:
        console.print(LOGO)
        console.print()
        console.print(f"[dim]Target:[/dim] [bold white]{args.url}[/bold white] [dim]|[/dim] [dim]Threads:[/dim] [white]{args.threads}[/white] [dim]|[/dim] [dim]Wordlist:[/dim] [white]{args.wordlist}[/white]\n")

    start_time = time.time()

    try:
        base_url = normalize_target(args.url)
        entries = load_wordlist(args.wordlist)
        status_filter = parse_status_codes(args.status)
        exclude_filter = parse_status_codes(args.exclude)
        extensions = parse_extensions(args.extensions)
        if args.delay < 0:
            raise ValueError("--delay must be >= 0")
        user_agent = args.user_agent
        if not user_agent or not user_agent.strip():
            raise ValueError("--user-agent must not be empty")
        method = parse_method(args.method)
        custom_headers = parse_headers(args.header)
    except (ValueError, FileNotFoundError) as exc:
        log.error(f"[bold red]✗[/bold red] {str(exc)}")
        return 2

    if not entries:
        log.error("[bold red]✗[/bold red] No wordlist entries were loaded.")
        return 2

    log.info(f"[bold blue]i[/bold blue] Starting discovery for [white]{len(entries)}[/white] paths...")

    hits: list = []

    def record_hit(result) -> None:
        hits.append(result)
        console.print(format_result(result), highlight=False)

    try:
        summary = asyncio.run(
            enumerate_directories(
                base_url=base_url,
                entries=entries,
                timeout=max(args.timeout, 0.1),
                threads=max(args.threads, 1),
                status_filter=status_filter,
                exclude_filter=exclude_filter,
                all_codes=args.all,
                proxy=args.proxy,
                max_retries=max(0, args.retries),
                extensions=extensions,
                on_result=record_hit,
                delay=args.delay,
                user_agent=user_agent,
                method=method,
                follow_redirects=args.follow_redirects,
                detect_wildcards=not args.no_wildcard,
                custom_headers=custom_headers,
            )
        )
    except KeyboardInterrupt:
        console.print(f"\n[bold red][!] Scan interrupted by user. Exiting...[/bold red]")
        return 130

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(render_plain_results(hits))
                if hits:
                    handle.write("\n")
        except OSError as exc:
            log.error(f"[bold red]✗[/bold red] Could not write output file: {exc}")
            return 2
        if not args.quiet:
            console.print(f"[dim]Saved {len(hits)} hit(s) to {args.output}[/dim]")

    duration = time.time() - start_time
    if not args.quiet:
        filtered_note = (
            f" ({summary.wildcard_filtered} hidden by wildcard filter)"
            if summary.wildcard_filtered
            else ""
        )
        console.print(f"\n[dim]Finished in {duration:.2f}s. Total hits: {summary.hits}{filtered_note}[/dim]")
        console.print(f"[dim]Progress: {summary.completed} / {summary.total} (100.00%)[/dim]")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
