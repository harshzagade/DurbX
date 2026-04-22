from __future__ import annotations

from colorama import Fore, Style, init

from .enumerator import ScanResult, should_show_result


init(autoreset=True)


def is_discovered(result: ScanResult) -> bool:
    return result.status_code is not None and 200 <= result.status_code < 400


def _color_for_status(status_code: int | None) -> str:
    if status_code == 200:
        return Fore.GREEN
    if status_code == 403:
        return Fore.YELLOW
    if status_code in {301, 302}:
        return Fore.MAGENTA
    if status_code is None:
        return Fore.RED
    return Fore.CYAN


def format_result(result: ScanResult) -> str:
    status = str(result.status_code) if result.status_code is not None else "-"
    size = f"{result.size}B"
    color = _color_for_status(result.status_code)
    if result.status_code in {200, 301, 302}:
        return color + f"{result.path:<20} {status:<5} {size:<10} -> {result.url}" + Style.RESET_ALL
    return color + f"{result.path:<20} {status:<5} {size:<10}" + Style.RESET_ALL


def render_results(results: list[ScanResult], status_filter: list[int] | None = None, exclude_filter: list[int] | None = None) -> str:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    visible = []
    for result in results:
        if not should_show_result(result, status_filter=status_filter, exclude_filter=exclude_filter):
            continue
        visible.append(result)

    if not visible:
        return "No directories discovered."

    lines = [f"{Style.BRIGHT}{'PATH':<20} {'CODE':<5} {'SIZE':<10} RESULT{Style.RESET_ALL}"]
    lines.extend(format_result(result) for result in visible)
    return "\n".join(lines)
