import logging
import argparse
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()

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
            ("-w, --wordlist", "Path to wordlist file"),
            ("-t, --threads", "Concurrent threads [dim](default: 50)[/dim]"),
        ],
        "FILTERS": [
            ("-a, --all", "Show all status codes [dim](except 404)[/dim]"),
            ("--status", "Show only these codes [dim](default: 200)[/dim]"),
            ("--exclude", "Exclude these codes [dim](e.g. 404,500)[/dim]"),
            ("--timeout", "Request timeout in seconds [dim](default: 3.0)[/dim]"),
            ("--retries", "Retry 429s with backoff [dim](default: 3; 0 disables)[/dim]"),
        ],
        "OUTPUT & LOGGING": [
            ("--proxy", "HTTP proxy URL"),
            ("-v, --verbose", "Enable detailed logging"),
            ("-q, --quiet", "Minimal output mode"),
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
    console.print("  [dim]$[/dim] durbx -u example.com -w words.txt --status 200,301")
    console.print("  [dim]$[/dim] durbx -u example.com -w words.txt -t 100 -q\n")
