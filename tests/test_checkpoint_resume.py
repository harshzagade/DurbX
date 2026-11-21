import asyncio
import json

import aiohttp
import pytest

from durbx.cli import main
from durbx.enumerator import (
    CHECKPOINT_VERSION,
    enumerate_directories,
    load_checkpoint,
    write_checkpoint,
)


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _write_words(tmp_path, words: str):
    path = tmp_path / "words.txt"
    path.write_text(words, encoding="utf-8")
    return path


def test_write_load_checkpoint_roundtrip(tmp_path) -> None:
    path = str(tmp_path / "cp.json")
    write_checkpoint(
        path,
        target="https://example.com",
        entries=["admin", "login"],
        completed=["admin"],
        finished=False,
    )
    loaded = load_checkpoint(path)
    assert loaded["tool"] == "durbx"
    assert loaded["checkpoint_version"] == CHECKPOINT_VERSION
    assert loaded["target"] == "https://example.com"
    assert loaded["entries"] == ["admin", "login"]
    assert loaded["completed"] == ["admin"]
    assert loaded["finished"] is False


def test_load_checkpoint_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_checkpoint(str(tmp_path / "nope.json"))


@pytest.mark.parametrize(
    "payload",
    [
        "{not json",
        json.dumps({"tool": "other", "checkpoint_version": CHECKPOINT_VERSION}),
        json.dumps({"tool": "durbx", "checkpoint_version": 999}),
        json.dumps(
            {
                "tool": "durbx",
                "checkpoint_version": CHECKPOINT_VERSION,
                "target": "https://example.com",
                # missing "entries", "completed", "finished"
            }
        ),
        json.dumps(["not", "an", "object"]),
    ],
)
def test_load_checkpoint_rejects_bad_payloads(tmp_path, payload) -> None:
    path = tmp_path / "cp.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_checkpoint(str(path))


def test_checkpoint_written_on_normal_scan(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = _write_words(tmp_path, "admin\nlogin\n")
    cp = str(tmp_path / "cp.json")
    rc = main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--checkpoint",
            cp,
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    loaded = load_checkpoint(cp)
    assert loaded["target"] == "https://example.com"
    assert loaded["entries"] == ["admin", "login"]
    assert sorted(loaded["completed"]) == ["admin", "login"]
    assert loaded["finished"] is True


def test_resume_skips_completed_entries(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = _write_words(tmp_path, "admin\nlogin\npanel\n")
    cp = str(tmp_path / "cp.json")
    write_checkpoint(
        cp,
        target="https://example.com",
        entries=["admin", "login", "panel"],
        completed=["admin"],
        finished=False,
    )
    rc = main(["--resume", cp, "-w", str(wordlist), "--no-wildcard", "-q"])
    assert rc == 0
    requested = [
        request[1]
        for session in aiohttp.ClientSession.instances
        for request in session.requests
    ]
    assert not any(url.endswith("/admin") for url in requested)
    assert any(url.endswith("/login") for url in requested)
    assert any(url.endswith("/panel") for url in requested)
    # Resume writes progress back to the checkpoint file; a finished scan is
    # marked so a second --resume refuses instead of re-scanning.
    loaded = load_checkpoint(cp)
    assert loaded["finished"] is True
    assert sorted(loaded["completed"]) == ["admin", "login", "panel"]


def test_resume_wordlist_mismatch_exit_2(tmp_path) -> None:
    wordlist = _write_words(tmp_path, "admin\nchanged\n")
    cp = str(tmp_path / "cp.json")
    write_checkpoint(
        cp,
        target="https://example.com",
        entries=["admin", "login"],
        completed=[],
        finished=False,
    )
    assert main(["--resume", cp, "-w", str(wordlist), "--no-wildcard", "-q"]) == 2


def test_resume_finished_checkpoint_exit_2(tmp_path) -> None:
    wordlist = _write_words(tmp_path, "admin\n")
    cp = str(tmp_path / "cp.json")
    write_checkpoint(
        cp,
        target="https://example.com",
        entries=["admin"],
        completed=["admin"],
        finished=True,
    )
    assert main(["--resume", cp, "-w", str(wordlist), "--no-wildcard", "-q"]) == 2


def test_resume_wrong_target_exit_2(tmp_path) -> None:
    wordlist = _write_words(tmp_path, "admin\n")
    cp = str(tmp_path / "cp.json")
    write_checkpoint(
        cp,
        target="https://example.com",
        entries=["admin"],
        completed=[],
        finished=False,
    )
    assert (
        main(
            ["--resume", cp, "-u", "other.example", "-w", str(wordlist), "--no-wildcard", "-q"]
        )
        == 2
    )


def test_resume_with_targets_exit_2(tmp_path) -> None:
    wordlist = _write_words(tmp_path, "admin\n")
    targets = tmp_path / "targets.txt"
    targets.write_text("example.com\n", encoding="utf-8")
    cp = str(tmp_path / "cp.json")
    write_checkpoint(
        cp,
        target="https://example.com",
        entries=["admin"],
        completed=[],
        finished=False,
    )
    assert (
        main(
            [
                "--resume",
                cp,
                "--targets",
                str(targets),
                "-w",
                str(wordlist),
                "--no-wildcard",
                "-q",
            ]
        )
        == 2
    )


def test_checkpoint_with_targets_exit_2(tmp_path) -> None:
    wordlist = _write_words(tmp_path, "admin\n")
    targets = tmp_path / "targets.txt"
    targets.write_text("one.example\ntwo.example\n", encoding="utf-8")
    assert (
        main(
            [
                "--targets",
                str(targets),
                "-w",
                str(wordlist),
                "--checkpoint",
                str(tmp_path / "cp.json"),
                "--no-wildcard",
                "-q",
            ]
        )
        == 2
    )


def test_cancelled_scan_writes_checkpoint(tmp_path) -> None:
    """Ctrl-C mid-scan persists progress: the checkpoint must carry the
    entries finished before the interrupt (not just the empty checkpoint
    written at scan start) and stay a valid resume point."""
    _reset_stub_sessions()
    entries = [f"w{i}" for i in range(50)]
    wordlist = _write_words(tmp_path, "\n".join(entries) + "\n")
    cp = str(tmp_path / "cp.json")
    # --delay 0.2 with one worker stretches the scan to ~10s; the 0.35s
    # timeout cancels it after a couple of entries — long after the
    # 10s periodic write could have fired, so any progress recorded
    # here came from the cancellation handler, not the periodic writer.
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            asyncio.wait_for(
                enumerate_directories(
                    base_url="https://example.com",
                    entries=entries,
                    detect_wildcards=False,
                    threads=1,
                    delay=0.2,
                    checkpoint_file=cp,
                    show_progress=False,
                ),
                timeout=0.35,
            )
        )
    loaded = load_checkpoint(cp)
    assert loaded["finished"] is False
    assert loaded["entries"] == entries
    assert 0 < len(loaded["completed"]) < len(entries)
    # The interrupted checkpoint is a real resume point: resuming
    # finishes the scan without re-requesting completed entries.
    rc = main(["--resume", cp, "-w", str(wordlist), "--no-wildcard", "-q"])
    assert rc == 0
    loaded = load_checkpoint(cp)
    assert loaded["finished"] is True
    assert sorted(loaded["completed"]) == sorted(entries)
    requested = [
        request[1]
        for session in aiohttp.ClientSession.instances
        for request in session.requests
    ]
    for done in loaded["completed"]:
        assert sum(1 for url in requested if url.endswith(f"/{done}")) == 1


def test_cancelled_scan_without_checkpoint_is_clean(tmp_path) -> None:
    """Cancelling a scan that has no checkpoint file must not raise
    anything from the checkpoint writer — it is a no-op there."""
    _reset_stub_sessions()
    entries = [f"w{i}" for i in range(50)]
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            asyncio.wait_for(
                enumerate_directories(
                    base_url="https://example.com",
                    entries=entries,
                    detect_wildcards=False,
                    threads=1,
                    delay=0.2,
                    show_progress=False,
                ),
                timeout=0.35,
            )
        )


def test_keyboard_interrupt_returns_130(tmp_path, monkeypatch) -> None:
    """The CLI catches KeyboardInterrupt from the scan and exits 130
    instead of leaking the traceback."""
    _reset_stub_sessions()
    wordlist = _write_words(tmp_path, "admin\nlogin\n")
    cp = str(tmp_path / "cp.json")

    import durbx.cli as cli_mod

    def _raise_keyboard_interrupt(*args, **kwargs):
        # The scan coroutine is created but never run under the stubbed
        # asyncio.run — close it so pytest does not warn about an
        # un-awaited coroutine.
        if args:
            args[0].close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_mod.asyncio, "run", _raise_keyboard_interrupt)
    assert (
        main(
            [
                "-u",
                "example.com",
                "-w",
                str(wordlist),
                "--checkpoint",
                cp,
                "--no-wildcard",
                "-q",
            ]
        )
        == 130
    )
