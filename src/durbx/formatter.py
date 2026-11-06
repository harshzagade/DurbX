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


def _retry_note(result: ScanResult) -> str:
    """`` (retried N)`` suffix for hits that needed 429 retries.

    ``attempts`` counts every request (first try + retries), so the
    number of retries is ``attempts - 1``; a single-attempt hit gets no
    note, keeping normal output byte-identical to before.
    """
    if result.attempts > 1:
        return f" (retried {result.attempts - 1})"
    return ""


def _listing_note(result: ScanResult) -> str:
    """`` (directory listing)`` suffix for hits whose 200 body looks like
    a server autoindex page; unflagged hits render exactly as before."""
    if result.is_directory_listing:
        return " (directory listing)"
    return ""


def _duplicate_note(result: ScanResult) -> str:
    """`` (xN identical bodies)`` suffix for a representative row that
    absorbed N-1 duplicate-body rows; a lone row renders exactly as
    before (duplicate_count defaults to 1)."""
    if result.duplicate_count > 1:
        return f" (x{result.duplicate_count} identical bodies)"
    return ""


def _url_suffix(result: ScanResult) -> str:
    """`` -> <destination>`` suffix for hits that carry a URL worth showing.

    A 3xx hit with a captured ``Location`` header points at its redirect
    target — previously the suffix just repeated the requested URL, which
    said nothing about where the redirect goes. Without a captured target
    (or for 200s), the suffix falls back to the requested URL as before,
    and other statuses get no suffix.
    """
    if (
        result.status_code is not None
        and 300 <= result.status_code < 400
        and result.redirect_target
    ):
        return f" -> {result.redirect_target}"
    if result.status_code in {200, 301, 302}:
        return f" -> {result.url}"
    return ""


def format_result(result: ScanResult) -> str:
    status = str(result.status_code) if result.status_code is not None else "-"
    size = f"{result.size}B"
    color = _color_for_status(result.status_code)
    line = f"{result.path:<20} {status:<5} {size:<10}{_retry_note(result)}{_listing_note(result)}{_duplicate_note(result)}"
    line += _url_suffix(result)
    return color + line + Style.RESET_ALL


def plain_result_line(result: ScanResult) -> str:
    """Single-line hit without ANSI colors, for output files and piping."""
    status = str(result.status_code) if result.status_code is not None else "-"
    size = f"{result.size}B"
    line = f"{result.path:<20} {status:<5} {size:<10}{_retry_note(result)}{_listing_note(result)}{_duplicate_note(result)}"
    line += _url_suffix(result)
    return line


def render_plain_results(results: list[ScanResult]) -> str:
    """Plain (uncolored) multi-line rendering of a hit list."""
    return "\n".join(plain_result_line(result) for result in results)


def format_status_breakdown(status_counts: dict[int, int] | None) -> str:
    """``200: 3, 403: 1`` breakdown of hit counts per status code.

    Codes sort ascending so the summary reads deterministically; an
    empty (or absent) breakdown renders as ``""`` so callers can omit
    the note entirely when there are no hits.
    """
    if not status_counts:
        return ""
    return ", ".join(
        f"{code}: {status_counts[code]}" for code in sorted(status_counts)
    )


def _aggregate_status_counts(summaries: list[ScanSummary]) -> dict[int, int]:
    """Sum per-status hit counts across per-target summaries."""
    totals: dict[int, int] = {}
    for summary in summaries:
        for code, count in (summary.status_counts or {}).items():
            totals[code] = totals.get(code, 0) + count
    return totals


def format_tech_headers_summary(tech_headers: dict[str, dict[str, int]] | None) -> str | None:
    """``Server: nginx/1.18 (2), Apache (1); X-Powered-By: PHP/8.1 (1)``.

    One group per header (headers sorted by name), values ranked by count
    descending then name so the most common server stands out. Empty
    input returns ``None`` so the caller omits the line entirely.
    """
    if not tech_headers:
        return None
    groups: list[str] = []
    for header_name in sorted(tech_headers):
        values = tech_headers[header_name]
        if not values:
            continue
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        groups.append(
            f"{header_name}: "
            + ", ".join(f"{value} ({count})" for value, count in ranked)
        )
    if not groups:
        return None
    return "; ".join(groups)


def _aggregate_tech_headers(summaries: list[ScanSummary]) -> dict[str, dict[str, int]]:
    """Sum per-value tech-header counts across per-target summaries."""
    totals: dict[str, dict[str, int]] = {}
    for summary in summaries:
        for header_name, values in (summary.tech_headers or {}).items():
            per_header = totals.setdefault(header_name, {})
            for value, count in values.items():
                per_header[value] = per_header.get(value, 0) + count
    return totals


def render_latency_summary(hits: list[ScanResult]) -> str | None:
    """``avg X ms; slowest: /a (Y ms), /b (Z ms)`` for the final summary.

    Only hits with a measured latency count toward the average or the
    slowest-3 list; when no hit carries a measurement there is nothing
    to summarize and this returns ``None`` so the caller omits the line.
    """
    measured = [hit for hit in hits if hit.latency_ms is not None]
    if not measured:
        return None
    average = sum(hit.latency_ms for hit in measured) / len(measured)
    slowest = sorted(measured, key=lambda hit: hit.latency_ms, reverse=True)[:3]
    slowest_text = ", ".join(
        f"{hit.path} ({hit.latency_ms:.1f}ms)" for hit in slowest
    )
    return f"avg {average:.1f}ms; slowest: {slowest_text}"


def render_json_report(
    hits_by_target: list[tuple[str, list[ScanResult]]],
    summaries: list[ScanSummary],
    duration: float,
) -> str:
    """Machine-readable JSON report for pipelines.

    Carries every hit (target, path, URL, status, reason, size, request
    attempts, redirect target) plus an
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
                    "attempts": hit.attempts,
                    "directory_listing": hit.is_directory_listing,
                    "redirect_target": hit.redirect_target,
                    "duplicate_count": hit.duplicate_count,
                    "latency_ms": (
                        round(hit.latency_ms, 2)
                        if hit.latency_ms is not None
                        else None
                    ),
                }
            )
    all_hits = [hit for _, target_hits in hits_by_target for hit in target_hits]
    measured = [hit for hit in all_hits if hit.latency_ms is not None]
    stats = {
        "targets": len(hits_by_target),
        "completed": sum(summary.completed for summary in summaries),
        "total": sum(summary.total for summary in summaries),
        "hits": sum(summary.hits for summary in summaries),
        "wildcard_filtered": sum(summary.wildcard_filtered for summary in summaries),
        "directory_listings": sum(summary.directory_listings for summary in summaries),
        "duplicate_bodies_collapsed": sum(
            summary.duplicate_bodies_collapsed for summary in summaries
        ),
        "tech_headers": _aggregate_tech_headers(summaries),
        "status_counts": _aggregate_status_counts(summaries),
        "avg_latency_ms": (
            round(sum(hit.latency_ms for hit in measured) / len(measured), 2)
            if measured
            else None
        ),
        "slowest_hits": [
            {
                "path": hit.path,
                "status_code": hit.status_code,
                "latency_ms": round(hit.latency_ms, 2),
            }
            for hit in sorted(
                measured, key=lambda hit: hit.latency_ms, reverse=True
            )[:3]
        ],
        "duration_seconds": round(duration, 2),
    }
    return json.dumps({"tool": "DurbX", "stats": stats, "results": results}, indent=2)


def render_results(results: list[ScanResult], status_filter: list[int] | None = None, exclude_filter: list[int] | None = None, filter_lengths: list[int] | None = None, match_lengths: list[int] | None = None) -> str:
    status_filter = status_filter or []
    exclude_filter = exclude_filter or []
    filter_lengths = filter_lengths or []
    match_lengths = match_lengths or []
    visible = []
    for result in results:
        if not should_show_result(result, status_filter=status_filter, exclude_filter=exclude_filter, filter_lengths=filter_lengths, match_lengths=match_lengths):
            continue
        visible.append(result)

    if not visible:
        return "No directories discovered."

    lines = [f"{Style.BRIGHT}{'PATH':<20} {'CODE':<5} {'SIZE':<10} RESULT{Style.RESET_ALL}"]
    lines.extend(format_result(result) for result in visible)
    return "\n".join(lines)
