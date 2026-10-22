import json

import aiohttp
import pytest

from durbx.cli import main
from durbx.enumerator import (
    CHECKPOINT_VERSION,
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
