import asyncio

import aiohttp

from durbx.cli import build_parser
from durbx.enumerator import (
    RANDOM_USER_AGENTS,
    UserAgentRotator,
    enumerate_directories,
    fetch_with_retry,
)


def _reset_stub_sessions() -> None:
    aiohttp.ClientSession.instances.clear()


def test_random_agent_cli_default_and_flag() -> None:
    parser = build_parser()
    args = parser.parse_args(["-u", "example.com", "-w", "custom.txt"])
    assert args.random_agent is False
    args = parser.parse_args(
        ["-u", "example.com", "-w", "custom.txt", "--random-agent"]
    )
    assert args.random_agent is True


def test_rotator_cycles_and_wraps() -> None:
    rotator = UserAgentRotator()
    seen = [rotator.next() for _ in range(len(RANDOM_USER_AGENTS) + 1)]
    assert seen[: len(RANDOM_USER_AGENTS)] == list(RANDOM_USER_AGENTS)
    assert seen[-1] == RANDOM_USER_AGENTS[0]
    assert len(RANDOM_USER_AGENTS) >= 4


def test_rotator_rejects_empty_pool() -> None:
    try:
        UserAgentRotator(())
    except ValueError:
        pass
    else:  # pragma: no cover - guard against a silent empty pool
        raise AssertionError("empty pool must fail fast")


def _request_user_agents() -> list:
    sessions = aiohttp.ClientSession.instances
    assert len(sessions) == 1
    agents = []
    for _, _, kwargs in sessions[0].requests:
        headers = kwargs.get("headers") or {}
        agents.append(headers.get("User-Agent"))
    return agents


def test_random_agent_rotates_per_scan_request() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin", "login"],
            threads=1,
            random_agent=True,
            detect_wildcards=False,
        )
    )
    # One request per entry, each with the next pool agent in order.
    assert _request_user_agents() == list(RANDOM_USER_AGENTS[:2])


def test_random_agent_overrides_fixed_user_agent() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin"],
            threads=1,
            user_agent="CustomScanner/2.0",
            random_agent=True,
            detect_wildcards=False,
        )
    )
    assert _request_user_agents() == [RANDOM_USER_AGENTS[0]]


def test_explicit_header_user_agent_wins_over_random_agent() -> None:
    _reset_stub_sessions()
    asyncio.run(
        enumerate_directories(
            base_url="http://example.com",
            entries=["admin"],
            threads=1,
            random_agent=True,
            custom_headers={"User-Agent": "Explicit/1.0"},
            detect_wildcards=False,
        )
    )
    # No per-request override: the session-level explicit header stands.
    assert _request_user_agents() == [None]
    assert aiohttp.ClientSession.instances[0].headers == {
        "User-Agent": "Explicit/1.0"
    }


def test_fetch_with_retry_passes_per_request_headers() -> None:
    seen: dict = {}

    class _FakeResponse:
        status = 200
        reason = "OK"
        headers = {"Content-Length": "2"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

    class _FakeSession:
        def request(self, method: str, url: str, **kwargs):
            seen.update(kwargs)
            return _FakeResponse()

    asyncio.run(
        fetch_with_retry(
            _FakeSession(),
            "https://example.com/admin",
            max_retries=0,
            headers={"User-Agent": RANDOM_USER_AGENTS[0]},
        )
    )
    assert seen["headers"] == {"User-Agent": RANDOM_USER_AGENTS[0]}
