import asyncio

import pytest

from durbx import enumerator as enumerator_mod
from durbx.cli import build_parser, main
from durbx.enumerator import (
    FetchOutcome,
    ScanResult,
    directory_prefix,
    enumerate_directories,
    is_directory_hit,
    parse_recurse_depth,
)


def _result(path, status, **kwargs):
    return ScanResult(
        path=path,
        status_code=status,
        url=f"https://example.com{path}",
        reason="OK",
        size=100,
        **kwargs,
    )


def test_parse_recurse_depth() -> None:
    assert parse_recurse_depth(None) == 0
    assert parse_recurse_depth("") == 0
    assert parse_recurse_depth("0") == 0
    assert parse_recurse_depth("1") == 1
    assert parse_recurse_depth("3") == 3


def test_parse_recurse_depth_rejects_junk() -> None:
    with pytest.raises(ValueError, match="Invalid recursion depth"):
        parse_recurse_depth("deep")
    with pytest.raises(ValueError, match="Invalid recursion depth"):
        parse_recurse_depth("-1")


def test_is_directory_hit() -> None:
    # Trailing-slash path that resolved.
    assert is_directory_hit(_result("/admin/", 200)) is True
    # Bare path that resolved is not a directory.
    assert is_directory_hit(_result("/admin", 200)) is False
    # A 301 to a trailing-slash target is a directory.
    assert is_directory_hit(_result("/old", 301, redirect_target="https://example.com/old/")) is True
    # A 301 to a bare file is not.
    assert is_directory_hit(_result("/old", 301, redirect_target="https://example.com/login")) is False
    # A 200 autoindex listing is a directory even without the slash.
    assert is_directory_hit(_result("/admin", 200, is_directory_listing=True)) is True
    # Unconfirmed statuses never recurse, even on a slash path.
    assert is_directory_hit(_result("/admin/", 403)) is False
    assert is_directory_hit(_result("/admin/", 404)) is False
    assert is_directory_hit(_result("/admin/", None)) is False


def test_directory_prefix() -> None:
    assert directory_prefix(_result("/admin/", 200), "https://example.com") == "/admin/"
    assert directory_prefix(_result("/admin", 200, is_directory_listing=True), "https://example.com") == "/admin/"
    assert directory_prefix(
        _result("/old", 301, redirect_target="https://example.com/old/"),
        "https://example.com",
    ) == "/old/"
    assert directory_prefix(
        _result("/old", 301, redirect_target="/old/"),
        "https://example.com",
    ) == "/old/"
    # An off-site redirect is not part of this target's tree.
    assert directory_prefix(
        _result("/old", 301, redirect_target="https://cdn.example.net/old/"),
        "https://example.com",
    ) is None
    # No directory signal at all.
    assert directory_prefix(_result("/admin", 200), "https://example.com") is None


def _routed_fetch(routes: dict, requested: list):
    async def fake_fetch(session, url, **kwargs):
        requested.append(url)
        outcome = routes.get(url)
        if outcome is None:
            return FetchOutcome(status=404, reason="Not Found", content_length=0, attempts=1)
        return outcome

    return fake_fetch


def _ok(size: int = 100, **kwargs) -> FetchOutcome:
    return FetchOutcome(status=200, reason="OK", content_length=size, attempts=1, **kwargs)


def _redirect(target: str) -> FetchOutcome:
    return FetchOutcome(
        status=301, reason="Moved Permanently", content_length=0,
        attempts=1, redirect_target=target,
    )


def test_recurse_one_level(monkeypatch) -> None:
    requested: list[str] = []
    routes = {
        "https://example.com/admin/": _ok(),
        "https://example.com/login": FetchOutcome(status=404, reason="Not Found", content_length=0, attempts=1),
        "https://example.com/admin/admin/": _ok(),
        "https://example.com/admin/login": _ok(),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    seen: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin/", "login"], threads=1,
        detect_wildcards=False, recurse_depth=1, on_result=seen.append,
    ))
    assert summary.hits == 3
    assert {hit.path for hit in seen} == {"/admin/", "/admin/admin/", "/admin/login"}
    assert summary.recursed_directories == 1
    assert summary.total == 4
    assert summary.completed == 4
    assert "https://example.com/admin/login" in requested


def test_recurse_off_by_default(monkeypatch) -> None:
    requested: list[str] = []
    routes = {
        "https://example.com/admin/": _ok(),
        "https://example.com/login": FetchOutcome(status=404, reason="Not Found", content_length=0, attempts=1),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin/", "login"], threads=1,
        detect_wildcards=False,
    ))
    assert summary.hits == 1
    assert summary.recursed_directories == 0
    assert summary.total == 2
    assert requested == [
        "https://example.com/admin/",
        "https://example.com/login",
    ]


def test_recurse_depth_caps_levels(monkeypatch) -> None:
    # /admin/ is a directory and so is /admin/admin/ — but with depth 1
    # the second level is scanned, never recursed into.
    requested: list[str] = []
    routes = {
        "https://example.com/admin/": _ok(),
        "https://example.com/admin/admin/": _ok(),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin/"], threads=1,
        detect_wildcards=False, recurse_depth=1,
    ))
    assert summary.hits == 2
    assert summary.recursed_directories == 1
    assert "https://example.com/admin/admin/admin/" not in requested


def test_recurse_follows_301_to_directory(monkeypatch) -> None:
    requested: list[str] = []
    routes = {
        "https://example.com/old": _redirect("https://example.com/old/"),
        "https://example.com/old/login": _ok(),
        "https://example.com/old/admin": FetchOutcome(status=404, reason="Not Found", content_length=0, attempts=1),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["old", "login"], threads=1,
        detect_wildcards=False, recurse_depth=1, status_filter=[200, 301],
    ))
    # The 301 itself is a hit (status filter includes it) and its target
    # is recursed into even though the default filter would hide 301s.
    assert summary.recursed_directories == 1
    assert "https://example.com/old/login" in requested


def test_recurse_301_recurses_even_when_status_filtered_out(monkeypatch) -> None:
    # Default status filter shows only 200s, so the 301 is not a hit —
    # but it still proves /old/ is a directory, so recursion happens and
    # the wordlist is replayed under it.
    requested: list[str] = []
    routes = {
        "https://example.com/old": _redirect("https://example.com/old/"),
        "https://example.com/login": FetchOutcome(status=404, reason="Not Found", content_length=0, attempts=1),
        "https://example.com/old/login": _ok(),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    seen: list[ScanResult] = []
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["old", "login"], threads=1,
        detect_wildcards=False, recurse_depth=1, on_result=seen.append,
    ))
    assert summary.hits == 1
    assert seen[0].path == "/old/login"
    assert summary.recursed_directories == 1


def test_recurse_two_levels(monkeypatch) -> None:
    requested: list[str] = []
    routes = {
        "https://example.com/a/": _ok(),
        "https://example.com/a/a/": _ok(),
        "https://example.com/a/a/a/": _ok(),
        "https://example.com/a/a/a/a/": _ok(),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["a/"], threads=1,
        detect_wildcards=False, recurse_depth=2,
    ))
    assert summary.hits == 3
    assert summary.recursed_directories == 2
    assert summary.total == 3
    assert "https://example.com/a/a/a/a/" not in requested


def test_recurse_never_requeues_a_scanned_entry(monkeypatch) -> None:
    # "admin/" recursed under itself would be "admin/admin/" — distinct.
    # But a wordlist entry equal to a discovered prefix must not loop:
    # "admin/" at level 1 is "admin/admin/", never "admin/" again, and
    # the level-2 "admin/admin/admin/" 404s, so the scan stops there.
    requested: list[str] = []
    routes = {
        "https://example.com/admin/": _ok(),
        "https://example.com/admin/admin/": _ok(),
    }
    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", _routed_fetch(routes, requested))
    summary = asyncio.run(enumerate_directories(
        "https://example.com", ["admin/"], threads=1,
        detect_wildcards=False, recurse_depth=5,
    ))
    assert requested.count("https://example.com/admin/") == 1
    assert summary.completed == 3
    assert summary.recursed_directories == 2


def test_recurse_with_checkpoint_raises(monkeypatch) -> None:
    async def fake_fetch(session, url, **kwargs):
        return FetchOutcome(status=200, reason="OK", content_length=10, attempts=1)

    monkeypatch.setattr(enumerator_mod, "fetch_with_retry", fake_fetch)
    with pytest.raises(ValueError, match="cannot be combined"):
        asyncio.run(enumerate_directories(
            "https://example.com", ["admin/"], threads=1,
            detect_wildcards=False, recurse_depth=1,
            checkpoint_file="/tmp/durbx-recurse-test.json",
        ))


def test_recurse_cli_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt", "--recurse", "2"])
    assert args.recurse == "2"
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.recurse is None


def test_recurse_cli_bad_depth_exit_2(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main(["-u", "example.com", "-w", str(wordlist), "--recurse", "deep", "--no-wildcard", "-q"])
    assert rc == 2


def test_recurse_cli_with_checkpoint_exit_2(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    rc = main([
        "-u", "example.com", "-w", str(wordlist),
        "--recurse", "1", "--checkpoint", str(tmp_path / "ck.json"),
        "--no-wildcard", "-q",
    ])
    assert rc == 2
