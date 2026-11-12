import logging
import argparse
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()


def set_no_color() -> Console:
    """Replace the shared console with one that emits no ANSI colors.

    Used by ``--no-color``: the banner, hit lines, and summary keep
    printing (unlike ``-q``, which suppresses them) — just without color,
    for clean piped logs. Returns the new console so callers that
    imported the old one by value (``cli.py``) can rebind theirs too.
    """
    global console
    console = Console(no_color=True)
    return console

LOGO = r"""
[bold blue]    ____             __   _  __[/bold blue]   [bold white]DurbX[/bold white] [dim]v0.1.0[/dim]
[bold blue]   / __ \__  _______/ /_ | |/ /[/bold blue]   [dim]Advanced Directory Discovery[/dim]
[bold blue]  / / / / / / / ___/ __ \|   / [/bold blue]   [bold white]by Harsh Zagade[/bold white]
[bold blue] / /_/ / /_/ / /  / /_/ /   |  [/bold blue]
[bold blue]/_____/\__,_/_/  /_.___/_/|_|  [/bold blue]
"""

class RichHelpCommand(argparse.HelpFormatter):
    """Custom formatter for professional help output."""
    pass

def setup_logging(verbose, quiet):
    log = logging.getLogger("durbx")
    if quiet:
        log.setLevel(logging.ERROR)
        log.addHandler(logging.NullHandler())
        log.propagate = False
        return log
    
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(
            rich_tracebacks=True, 
            console=console, 
            show_path=False,
            markup=True,
            highlighter=None
        )]
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    
    return log

def print_help():
    console.print(f"\n{LOGO}")
    console.print(f"\n[bold white]USAGE[/bold white]")
    console.print(r"  $ durbx [dim]\[options][/dim] -u <url> -w <wordlist>")
    
    groups = {
        "CORE SETTINGS": [
            ("-u, --url", "Target URL [dim](e.g. https://example.com)[/dim]"),
            ("--targets", "Target list file [dim](one URL per line; use instead of -u)[/dim]"),
            ("-w, --wordlist", "Path to wordlist file [dim](use - for stdin)[/dim]"),
            ("--stdin", "Read candidate paths from stdin [dim](instead of a wordlist file)[/dim]"),
            ("-x, --extensions", "Append extensions to each word [dim](e.g. php,html)[/dim]"),
            ("-t, --threads", "Concurrent threads [dim](default: 50)[/dim]"),
            ("--delay", "Pause between requests per worker [dim](default: 0)[/dim]"),
            ("--rate-limit", "Global requests-per-second cap [dim](shared across workers)[/dim]"),
            ("--user-agent", "Custom User-Agent header [dim](default: DurbX/0.1)[/dim]"),
            ("--random-agent", "Rotate User-Agent per request [dim](built-in browser list)[/dim]"),
            ("-H, --header", "Custom HTTP header [dim](repeatable; overrides --user-agent)[/dim]"),
            ("-m, --method", "HTTP request method [dim](GET/HEAD/POST; default: GET)[/dim]"),
        ],
        "FILTERS": [
            ("-a, --all", "Show all status codes [dim](except 404)[/dim]"),
            ("--status", "Show only these codes [dim](default: 200; ranges like 200-299)[/dim]"),
            ("--exclude", "Exclude these codes [dim](e.g. 404,500; ranges like 500-599)[/dim]"),
            ("--filter-length", "Hide responses with these body sizes [dim](e.g. 1234,5678)[/dim]"),
            ("--match-length", "Show only responses with these body sizes [dim](e.g. 1234,5678)[/dim]"),
            ("--exclude-path", "Skip wordlist entries matching a regex [dim](repeatable; before -x expansion)[/dim]"),
            ("--timeout", "Request timeout in seconds [dim](default: 3.0)[/dim]"),
            ("--retries", "Retry retryable statuses with backoff [dim](default: 3; 0 disables)[/dim]"),
            ("--retry-on", "Statuses to retry like 429 [dim](e.g. 500,502,503; default: 429 only)[/dim]"),
            ("--no-wildcard", "Disable soft-404 wildcard detection"),
            ("--follow-redirects", "Follow 3xx redirects [dim](default: report them)[/dim]"),
        ],
        "OUTPUT & LOGGING": [
            ("--proxy", "HTTP proxy URL"),
            ("-o, --output", "Save hits to a file"),
            ("--json", "Save a machine-readable JSON report (hits + stats) to a file"),
            ("--csv", "Save a CSV report (one row per hit) to a file"),
            ("--sort", "Sort hits by path in -o/--json/--csv output [dim](per target; live terminal lines stay in completion order)[/dim]"),
            ("--checkpoint", "Write resume checkpoints during the scan [dim](single-target)[/dim]"),
            ("--resume", "Resume an interrupted scan from a checkpoint [dim](single-target)[/dim]"),
            ("-v, --verbose", "Enable detailed logging"),
            ("-q, --quiet", "Minimal output mode"),
            ("--no-color", "Disable ANSI colors in terminal output [dim](banner, hits, summary; unlike -q, output still prints)[/dim]"),
            ("-h, --help", "Show this help message"),
        ]
    }

    for group, options in groups.items():
        table = Table(box=None, expand=False, show_header=False, pad_edge=False)
        table.add_column("Option", style="blue", width=24)
        table.add_column("Description", style="white")
        
        for opt, desc in options:
            table.add_row(f"  {opt}", desc)
            
        console.print(f"\n[bold white]{group}[/bold white]")
        console.print(table)
        
    console.print(f"\n[bold white]EXAMPLES[/bold white]")
    console.print("  [dim]$[/dim] durbx -u https://example.com -w common.txt")
    console.print("  [dim]$[/dim] durbx --targets targets.txt -w common.txt -q")
    console.print("  [dim]$[/dim] durbx -u example.com -w words.txt --status 200,301")
    console.print("  [dim]$[/dim] durbx -u example.com -w words.txt -t 100 -q\n")
