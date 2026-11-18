import aiohttp
import pytest

from durbx.cli import build_parser, main
from durbx.enumerator import build_basic_auth_header


def test_build_basic_auth_header_encodes_credentials() -> None:
    # "user:pass" base64-encodes to dXNlcjpwYXNz.
    assert build_basic_auth_header("user:pass") == "Basic dXNlcjpwYXNz"


def test_build_basic_auth_header_password_may_contain_colons() -> None:
    # Split on the first ':' only; "user:a:b" is the literal credential.
    assert build_basic_auth_header("user:a:b") == "Basic dXNlcjphOmI="


def test_build_basic_auth_header_empty_password_allowed() -> None:
    assert build_basic_auth_header("user:") == "Basic dXNlcjo="


def test_build_basic_auth_header_empty_is_none() -> None:
    assert build_basic_auth_header(None) is None
    assert build_basic_auth_header("") is None


def test_build_basic_auth_header_rejects_malformed() -> None:
    bad = [
        "user",  # no ':'
        ":pass",  # empty user
        "user name:pass",  # space in user
        "user:pa ss",  # space in password
        "user:pa\tss",  # tab in password
    ]
    for item in bad:
        with pytest.raises(ValueError):
            build_basic_auth_header(item)


def test_cli_accepts_basic_auth_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["-u", "example.com", "-w", "words.txt", "--basic-auth", "user:pass"]
    )
    assert args.basic_auth == "user:pass"


def test_cli_basic_auth_flag_defaults_none() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "words.txt"])
    assert args.basic_auth is None


def _run_main(tmp_path, *extra_args) -> int:
    """Run the CLI against the stub session (answers 200 to everything)
    and return the exit code."""
    aiohttp.ClientSession.instances.clear()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    return main(
        ["-u", "example.com", "-w", str(wordlist), "--no-wildcard", "-q", *extra_args]
    )


def test_main_basic_auth_reaches_session_headers(tmp_path) -> None:
    assert _run_main(tmp_path, "--basic-auth", "user:pass") == 0
    session = aiohttp.ClientSession.instances[-1]
    assert session.headers["Authorization"] == "Basic dXNlcjpwYXNz"
    assert session.headers["User-Agent"] == "DurbX/0.1"


def test_main_explicit_header_authorization_wins(tmp_path) -> None:
    assert (
        _run_main(
            tmp_path,
            "--basic-auth",
            "user:from-flag",
            "-H",
            "Authorization: Bearer from-header",
        )
        == 0
    )
    session = aiohttp.ClientSession.instances[-1]
    assert session.headers["Authorization"] == "Bearer from-header"


def test_main_bad_basic_auth_exits_2(tmp_path) -> None:
    assert _run_main(tmp_path, "--basic-auth", "user") == 2
    assert _run_main(tmp_path, "--basic-auth", ":pass") == 2
