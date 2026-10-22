from __future__ import annotations

import json

from colorama import Fore, Style, init

from .enumerator import ScanResult, ScanSummary, should_show_result


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


def plain_result_line(result: ScanResult) -> str:
    """Single-line hit without ANSI colors, for output files and piping."""
    status = str(result.status_code) if result.status_code is not None else "-"
    size = f"{result.size}B"
    line = f"{result.path:<20} {status:<5} {size:<10}"
    if result.status_code in {200, 301, 302}:
        line += f" -> {result.url}"
    return line


def render_plain_results(results: list[ScanResult]) -> str:
    """Plain (uncolored) multi-line rendering of a hit list."""
    return "\n".join(plain_result_line(result) for result in results)


def render_json_report(
    hits_by_target: list[tuple[str, list[ScanResult]]],
    summaries: list[ScanSummary],
    duration: float,
) -> str:
    """Machine-readable JSON report for pipelines.

    Carries every hit (target, path, URL, status, reason, size) plus an
    aggregate ``stats`` block — completed/total counts, hit count,
    wildcard-filtered count, and scan duration — so CI and recon pipelines
    can consume results without parsing terminal output.
    """
    results: list[dict] = []
    for target, target_hits in hits_by_target:
        for hit in target_hits:
            results.append(
                {
                    "target": target,
                    "path": hit.path,
                    "url": hit.url,
                    "status_code": hit.status_code,
                    "reason": hit.reason,
                    "size": hit.size,
                }
            )
    stats = {
        "targets": len(hits_by_target),
        "completed": sum(summary.completed for summary in summaries),
        "total": sum(summary.total for summary in summaries),
        "hits": sum(summary.hits for summary in summaries),
        "wildcard_filtered": sum(summary.wildcard_filtered for summary in summaries),
        "duration_seconds": round(duration, 2),
    }
    return json.dumps({"tool": "DurbX", "stats": stats, "results": results}, indent=2)


def render_results(results: list[ScanResult], status_filter: list[int] | None = None, exclude_filter: list[int] | None = None, filter_lengths: list[int] | None = None) -> str:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    filter_lengths = filter_lengths or []
    visible = []
    for result in results:
        if not should_show_result(result, status_filter=status_filter, exclude_filter=exclude_filter, filter_lengths=filter_lengths):
            continue
        visible.append(result)

    if not visible:
        return "No directories discovered."

    lines = [f"{Style.BRIGHT}{'PATH':<20} {'CODE':<5} {'SIZE':<10} RESULT{Style.RESET_ALL}"]
    lines.extend(format_result(result) for result in visible)
    return "\n".join(lines)
