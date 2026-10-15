from __future__ import annotations

import logging
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Fallback stubs for third-party deps (aiohttp / rich / colorama).
#
# This environment has no network installs (Harsh's rule: nothing installed
# without his word), so when the real packages are unavailable the suite
# falls back to stdlib-only stubs. If the real packages ARE importable they
# take precedence and the stubs are never installed.
# ---------------------------------------------------------------------------

def _make_aiohttp_stub() -> types.ModuleType:
    mod = types.ModuleType("aiohttp")

    class ClientError(Exception):
        """Base aiohttp client error (stub)."""

    class ClientConnectionError(ClientError):
        """Raised when a connection fails (stub)."""

    class _StubResponse:
        def __init__(self, status: int = 200, reason: str = "OK", headers: dict | None = None) -> None:
            self.status = status
            self.reason = reason
            self.headers = headers if headers is not None else {"Content-Length": "2"}

        async def __aenter__(self) -> "_StubResponse":
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

    class ClientSession:
        """Records constructor args; `get()` returns a canned 200 response."""

        instances: list = []

        def __init__(self, connector=None, timeout=None, headers=None) -> None:
            self.connector = connector
            self.timeout = timeout
            self.headers = dict(headers or {})
            self.get_count = 0
            type(self).instances.append(self)

        async def __aenter__(self) -> "ClientSession":
            return self

        async def __aexit__(self, *exc_info) -> bool:
            return False

        def get(self, url: str, **kwargs):
            self.get_count += 1
            return _StubResponse()

    class ClientTimeout:
        def __init__(self, total=None) -> None:
            self.total = total

    class TCPConnector:
        def __init__(self, **kwargs) -> None:
            pass

    mod.ClientError = ClientError
    mod.ClientConnectionError = ClientConnectionError
    mod.ClientSession = ClientSession
    mod.ClientTimeout = ClientTimeout
    mod.TCPConnector = TCPConnector
    return mod


def _make_colorama_stub() -> types.ModuleType:
    mod = types.ModuleType("colorama")

    class _Colors:
        GREEN = ""
        YELLOW = ""
        MAGENTA = ""
        RED = ""
        CYAN = ""
        WHITE = ""
        BLUE = ""

    class _Style:
        BRIGHT = ""
        RESET_ALL = ""

    mod.Fore = _Colors()
    mod.Style = _Style()
    mod.init = lambda *args, **kwargs: None
    return mod


def _make_rich_stubs() -> None:
    rich_mod = types.ModuleType("rich")
    console_mod = types.ModuleType("rich.console")
    logging_mod = types.ModuleType("rich.logging")
    table_mod = types.ModuleType("rich.table")

    class Console:
        def print(self, *args, **kwargs) -> None:
            pass

        def log(self, *args, **kwargs) -> None:
            pass

    class RichHandler(logging.Handler):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__()

        def emit(self, record) -> None:
            pass

    class Table:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_column(self, *args, **kwargs) -> None:
            pass

        def add_row(self, *args, **kwargs) -> None:
            pass

    console_mod.Console = Console
    logging_mod.RichHandler = RichHandler
    table_mod.Table = Table
    rich_mod.console = console_mod
    rich_mod.logging = logging_mod
    rich_mod.table = table_mod
    sys.modules["rich"] = rich_mod
    sys.modules["rich.console"] = console_mod
    sys.modules["rich.logging"] = logging_mod
    sys.modules["rich.table"] = table_mod


def _ensure_dependency(name: str, factory) -> None:
    if name in sys.modules:
        return
    try:
        __import__(name)
    except ImportError:
        produced = factory()
        if produced is not None:
            sys.modules[name] = produced


_ensure_dependency("aiohttp", _make_aiohttp_stub)
_ensure_dependency("colorama", _make_colorama_stub)
_ensure_dependency("rich", _make_rich_stubs)
