import aiohttp

from durbx.cli import main


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def _run_fail_on(tmp_path, *extra_args) -> int:
    """Run the CLI against the stub session (which answers 200 to every
    request) with a one-word wordlist, returning the exit code."""
    _reset_stub_sessions()
    wordlist = tmp_path / "words.txt"
    wordlist.write_text("admin\n", encoding="utf-8")
    return main(
        [
            "-u",
            "example.com",
            "-w",
            str(wordlist),
            "--no-wildcard",
            "-q",
            *extra_args,
        ]
    )


def test_fail_on_matching_status_exits_1(tmp_path) -> None:
    # The stub answers 200, so --fail-on 200 must fail the run.
    assert _run_fail_on(tmp_path, "--fail-on", "200") == 1


def test_fail_on_non_matching_status_exits_0(tmp_path) -> None:
    assert _run_fail_on(tmp_path, "--fail-on", "403") == 0
    assert _run_fail_on(tmp_path, "--fail-on", "500-599") == 0


def test_fail_on_accepts_lists_and_ranges(tmp_path) -> None:
    assert _run_fail_on(tmp_path, "--fail-on", "403,200") == 1
    assert _run_fail_on(tmp_path, "--fail-on", "200-299") == 1


def test_fail_on_invalid_code_exits_2(tmp_path) -> None:
    assert _run_fail_on(tmp_path, "--fail-on", "abc") == 2
    assert _run_fail_on(tmp_path, "--fail-on", "299-200") == 2


def test_no_fail_on_flag_exits_0(tmp_path) -> None:
    assert _run_fail_on(tmp_path) == 0
