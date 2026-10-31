import aiohttp

from durbx.cli import build_parser, main


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _run(tmp_path, extra_args):
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "hits.txt"
    rc = main(
        ["-u", "example.com", "-w", str(wordlist), "-o", str(out),
         "--no-wildcard", "-q"] + extra_args
    )
    assert rc == 0
    return out


def test_append_flag_default_and_set() -> None:
    parser = build_parser()
    assert parser.parse_args(["-u", "example.com", "-w", "w.txt"]).append is False
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt", "-o", "h.txt", "--append"])
    assert args.append is True


def test_append_without_output_exits_2(tmp_path) -> None:
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    assert main(["-u", "example.com", "-w", str(wordlist), "--append", "-q"]) == 2


def test_append_preserves_existing_hits(tmp_path) -> None:
    _reset_stub_sessions()
    out = _run(tmp_path, ["--append"])
    # First run created the file (append to a missing file == create).
    assert "https://example.com/admin" in out.read_text(encoding="utf-8")
    _reset_stub_sessions()
    out2 = _run(tmp_path, ["--append"])
    assert out2 is out or out2.read_text(encoding="utf-8").count(
        "https://example.com/admin") == 2


def test_append_separates_when_existing_file_lacks_trailing_newline(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "hits.txt"
    out.write_text("old hit (no newline)", encoding="utf-8")
    rc = main(["-u", "example.com", "-w", str(wordlist), "-o", str(out),
               "--append", "--no-wildcard", "-q"])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "old hit (no newline)"
    assert any("https://example.com/admin" in line for line in lines[1:])


def test_output_without_append_overwrites(tmp_path) -> None:
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    out = tmp_path / "hits.txt"
    out.write_text("stale hit\n", encoding="utf-8")
    rc = main(["-u", "example.com", "-w", str(wordlist), "-o", str(out),
               "--no-wildcard", "-q"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "stale hit" not in text
    assert "https://example.com/admin" in text
