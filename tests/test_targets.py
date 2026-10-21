import aiohttp
import pytest

from durbx.cli import build_parser, main
from durbx.enumerator import load_targets


def _write(path, text: str):
    path.write_text(text, encoding="utf-8")
    return path


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_load_targets_skips_blanks_comments_and_dedupes(tmp_path) -> None:
    file = _write(
        tmp_path / "targets.txt",
        "# comment\nexample.com\n\nhttps://example.com/\nhttp://other.com\n",
    )
    assert load_targets(str(file)) == ["https://example.com", "http://other.com"]


def test_load_targets_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_targets(str(tmp_path / "nope.txt"))


def test_load_targets_invalid_line_names_line_number(tmp_path) -> None:
    file = _write(tmp_path / "targets.txt", "example.com\nhttp://\nexample.org\n")
    with pytest.raises(ValueError, match="line 2"):
        load_targets(str(file))


def test_targets_flag_and_url_optional() -> None:
    parser = build_parser()
    args = parser.parse_args(["--targets", "t.txt", "-w", "w.txt"])
    assert args.targets == "t.txt"
    assert args.url is None
    args = parser.parse_args(["-u", "example.com", "-w", "w.txt"])
    assert args.targets is None


def test_url_and_targets_together_exit_2() -> None:
    assert main(["-u", "example.com", "--targets", "t.txt", "-w", "w.txt"]) == 2


def test_neither_url_nor_targets_exit_2() -> None:
    assert main(["-w", "w.txt"]) == 2


def test_main_scans_multiple_targets_sequentially(tmp_path) -> None:
    _reset_stub_sessions()
    targets = _write(tmp_path / "targets.txt", "one.example\ntwo.example\n")
    wordlist = _write(tmp_path / "words.txt", "admin\n")
    out = tmp_path / "hits.txt"
    rc = main(
        [
            "--targets",
            str(targets),
            "-w",
            str(wordlist),
            "-o",
            str(out),
            "--no-wildcard",
            "-q",
        ]
    )
    assert rc == 0
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 2
    requested_urls = [request[1] for session in sessions for request in session.requests]
    assert any(url.startswith("https://one.example/") for url in requested_urls)
    assert any(url.startswith("https://two.example/") for url in requested_urls)
    text = out.read_text(encoding="utf-8")
    assert "# Target: https://one.example" in text
    assert "# Target: https://two.example" in text
    assert "https://one.example/admin" in text
    assert "https://two.example/admin" in text
