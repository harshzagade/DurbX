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
    expand_extensions,
    load_checkpoint,
    load_stdin_entries,
    load_targets,
    load_wordlist,
    normalize_target,
    parse_extensions,
    parse_filter_lengths,
    parse_headers,
    parse_match_lengths,
    parse_method,
    parse_rate_limit,
    parse_status_codes,
)
from .formatter import format_result, render_json_report, render_plain_results
from .utils import LOGO, setup_logging, console, print_help


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="durbx",
        description="DurbX - Directory Enumeration Tool",
        add_help=False
    )
    parser.add_argument("-u", "--url", help="Target URL (use --targets for many)")
    parser.add_argument("--targets", help="File with target URLs, one per line (use instead of -u)")
    parser.add_argument("-w", "--wordlist", help="Wordlist file to use (use - for stdin)")
    parser.add_argument("--stdin", action="store_true", help="Read candidate paths from stdin instead of a wordlist file")
    parser.add_argument("-x", "--extensions", help="Append file extensions to each word (e.g. php,html)")
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS, help=f"Threads (default: {DEFAULT_THREADS})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES, help=f"Retries on HTTP 429 with backoff (default: {DEFAULT_MAX_RETRIES}; 0 disables)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Pause in seconds between requests per worker (default: {DEFAULT_DELAY}; for stealthy/rate-limited targets)")
    parser.add_argument("--rate-limit", type=float, default=None, help="Global requests-per-second cap shared across workers (e.g. 10; complements --delay)")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help=f"Custom User-Agent header (default: {DEFAULT_USER_AGENT})")
    parser.add_argument("-H", "--header", action="append", default=None, help="Custom HTTP header, e.g. -H 'Authorization: Bearer abc' (repeatable; overrides --user-agent)")
    parser.add_argument("-m", "--method", default=DEFAULT_METHOD, help=f"HTTP method for requests (default: {DEFAULT_METHOD}; GET/HEAD/POST)")
    parser.add_argument("--follow-redirects", action="store_true", help="Follow 3xx redirects instead of reporting them (default: no)")
    parser.add_argument("--status", help="Show only these codes (e.g. 200,403 or ranges like 200-299)")
    parser.add_argument("--exclude", help="Exclude codes (e.g. 404,500 or ranges like 500-599)")
    parser.add_argument("--filter-length", help="Hide responses with these body sizes in bytes (e.g. 1234,5678)")
    parser.add_argument("--match-length", help="Show only responses with these body sizes in bytes (e.g. 1234,5678)")
    parser.add_argument("-a", "--all", action="store_true", help="Show all status codes (except 404)")
    parser.add_argument("--no-wildcard", action="store_true", help="Disable soft-404 wildcard detection")
    parser.add_argument("--proxy", help="Proxy URL (e.g. http://127.0.0.1:8080)")
    parser.add_argument("-o", "--output", help="Save discovered hits to a file")
    parser.add_argument("--json", metavar="FILE", help="Save a machine-readable JSON report (hits + stats) to a file")
    parser.add_argument("--checkpoint", metavar="FILE", help="Write resume checkpoints during the scan (single-target runs)")
    parser.add_argument("--resume", metavar="FILE", help="Resume an interrupted scan from a checkpoint file (single-target)")
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

    try:
        if args.url and args.targets:
            raise ValueError("Use either -u/--url or --targets, not both")
        if args.targets:
            base_urls = load_targets(args.targets)
        elif args.url:
            base_urls = [normalize_target(args.url)]
        elif args.resume:
            base_urls = []  # resolved from the checkpoint below
        else:
            raise ValueError("A target is required: use -u/--url or --targets FILE")
        if not base_urls and not args.resume:
            raise ValueError("The targets file contained no valid targets")
        if args.stdin and args.wordlist and args.wordlist != "-":
            raise ValueError("Use either --stdin or -w/--wordlist, not both")
        if args.stdin or args.wordlist == "-":
            entries = load_stdin_entries()
        elif args.wordlist:
            entries = load_wordlist(args.wordlist)
        else:
            raise ValueError("A wordlist is required: use -w/--wordlist FILE, -w -, or --stdin")
        if not entries:
            raise ValueError("No wordlist entries were loaded.")
        status_filter = parse_status_codes(args.status)
        exclude_filter = parse_status_codes(args.exclude)
        filter_lengths = parse_filter_lengths(args.filter_length)
        match_lengths = parse_match_lengths(args.match_length)
        extensions = parse_extensions(args.extensions)
        if args.delay < 0:
            raise ValueError("--delay must be >= 0")
        rate_limit = parse_rate_limit(args.rate_limit)
        user_agent = args.user_agent
        if not user_agent or not user_agent.strip():
            raise ValueError("--user-agent must not be empty")
        method = parse_method(args.method)
        custom_headers = parse_headers(args.header)
    except (ValueError, FileNotFoundError) as exc:
        log.error(f"[bold red]✗[/bold red] {str(exc)}")
        return 2

    resume_completed: list[str] = []
    if args.checkpoint and len(base_urls) > 1:
        log.error("[bold red]✗[/bold red] --checkpoint only supports single-target scans, not --targets")
        return 2
    if args.resume:
        if args.targets:
            log.error("[bold red]✗[/bold red] --resume only supports single-target scans, not --targets")
            return 2
        try:
            checkpoint = load_checkpoint(args.resume)
        except (ValueError, FileNotFoundError) as exc:
            log.error(f"[bold red]✗[/bold red] Cannot resume: {exc}")
            return 2
        if checkpoint["finished"]:
            log.error("[bold red]✗[/bold red] Checkpoint scan already finished — nothing to resume")
            return 2
        checkpoint_target = checkpoint["target"]
        if args.url and normalize_target(args.url) != checkpoint_target:
            log.error("[bold red]✗[/bold red] -u/--url does not match the checkpoint's target")
            return 2
        base_urls = [checkpoint_target]
        # The resumed scan must cover exactly the entries the checkpoint was
        # written for (same wordlist + extensions); anything else means the
        # progress record no longer describes this scan.
        expanded = expand_extensions(entries, extensions)
        if expanded != checkpoint["entries"]:
            log.error("[bold red]✗[/bold red] Wordlist/extensions do not match the checkpoint — cannot resume")
            return 2
        done = set(checkpoint["completed"])
        resume_completed = checkpoint["completed"]
        entries = [entry for entry in expanded if entry not in done]
        extensions = []
        if not entries:
            if not args.quiet:
                console.print("[dim]All checkpoint entries already scanned — nothing to resume.[/dim]")
            return 0
        if not args.quiet:
            console.print(f"[dim]Resuming from checkpoint: {len(done)} of {len(expanded)} entries already done.[/dim]")

    wordlist_label = "stdin" if (args.stdin or args.wordlist == "-") else args.wordlist
    if not args.quiet:
        console.print(LOGO)
        console.print()
        if len(base_urls) == 1:
            console.print(f"[dim]Target:[/dim] [bold white]{base_urls[0]}[/bold white] [dim]|[/dim] [dim]Threads:[/dim] [white]{args.threads}[/white] [dim]|[/dim] [dim]Wordlist:[/dim] [white]{wordlist_label}[/white]\n")
        else:
            console.print(f"[dim]Targets:[/dim] [bold white]{len(base_urls)}[/bold white] [dim]from[/dim] [white]{args.targets}[/white] [dim]|[/dim] [dim]Threads:[/dim] [white]{args.threads}[/white] [dim]|[/dim] [dim]Wordlist:[/dim] [white]{wordlist_label}[/white]\n")

    start_time = time.time()

    hits: list = []
    summaries: list = []
    hits_by_target: list[tuple[str, list]] = []

    def record_hit(result) -> None:
        hits.append(result)
        console.print(format_result(result), highlight=False)

    try:
        for index, base_url in enumerate(base_urls, start=1):
            if len(base_urls) > 1 and not args.quiet:
                console.print(f"\n[dim]Target {index}/{len(base_urls)}:[/dim] [bold white]{base_url}[/bold white]\n")
            log.info(f"[bold blue]i[/bold blue] Starting discovery for [white]{len(entries)}[/white] paths...")
            before = len(hits)
            summaries.append(
                asyncio.run(
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
                        filter_lengths=filter_lengths,
                        match_lengths=match_lengths,
                        checkpoint_file=args.checkpoint or args.resume,
                        resume_completed=resume_completed,
                        rate_limit=rate_limit,
                    )
                )
            )
            hits_by_target.append((base_url, hits[before:]))
    except KeyboardInterrupt:
        console.print(f"\n[bold red][!] Scan interrupted by user. Exiting...[/bold red]")
        return 130

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as handle:
                for base_url, target_hits in hits_by_target:
                    if len(base_urls) > 1:
                        handle.write(f"# Target: {base_url}\n")
                    if target_hits:
                        handle.write(render_plain_results(target_hits))
                        handle.write("\n")
                    if len(base_urls) > 1:
                        handle.write("\n")
        except OSError as exc:
            log.error(f"[bold red]✗[/bold red] Could not write output file: {exc}")
            return 2
        if not args.quiet:
            console.print(f"[dim]Saved {len(hits)} hit(s) to {args.output}[/dim]")

    duration = time.time() - start_time

    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as handle:
                handle.write(render_json_report(hits_by_target, summaries, duration))
                handle.write("\n")
        except OSError as exc:
            log.error(f"[bold red]✗[/bold red] Could not write JSON report: {exc}")
            return 2
        if not args.quiet:
            console.print(f"[dim]Saved JSON report to {args.json}[/dim]")

    if not args.quiet:
        total_hits = sum(summary.hits for summary in summaries)
        total_filtered = sum(summary.wildcard_filtered for summary in summaries)
        total_completed = sum(summary.completed for summary in summaries)
        total_scanned = sum(summary.total for summary in summaries)
        filtered_note = (
            f" ({total_filtered} hidden by wildcard filter)"
            if total_filtered
            else ""
        )
        if len(base_urls) > 1:
            console.print(f"\n[dim]Finished in {duration:.2f}s. Total hits across {len(base_urls)} targets: {total_hits}{filtered_note}[/dim]")
        else:
            console.print(f"\n[dim]Finished in {duration:.2f}s. Total hits: {total_hits}{filtered_note}[/dim]")
        console.print(f"[dim]Progress: {total_completed} / {total_scanned} (100.00%)[/dim]")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
