"""Session-wide test fixtures, at the repository root on purpose.

`testpaths` covers both `tests/` and the package trees, because L0 §1 puts unit tests
beside the code they test. A `conftest.py` only applies to its own directory downwards, so
the environment isolation and the offline guard live here rather than in `tests/`: a unit
test sitting next to `pipeline/schema/record.py` needs both just as much (review C5).
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

#: Loopback only. DuckDB, pyarrow and a live FastAPI TestClient may all legitimately open a
#: local socket; nothing in this project may open a remote one from a test.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "::ffff:127.0.0.1"})


class OutboundNetworkError(RuntimeError):
    """A test tried to open a socket to something that is not loopback."""


def _is_local(sock: socket.socket, address: Any) -> bool:
    if sock.family == getattr(socket, "AF_UNIX", object()):
        return True
    if isinstance(address, (str, bytes)):  # AF_UNIX path
        return True
    if isinstance(address, tuple) and address:
        host = str(address[0])
        return host in _LOOPBACK_HOSTS or host.startswith("127.")
    return False


@pytest.fixture(scope="session", autouse=True)
def _no_outbound_network() -> Iterator[None]:
    """The suite runs offline. Every test, everywhere in the tree.

    L0 and SF-07 say the tests make no external calls, but that was prose: nothing enforced
    it, and "GitHub runners have no egress" is not something this project gets to assume
    (review C5). An accidental live adapter call would otherwise pass CI, quietly depend on
    a third party, and spend real API budget.

    Limit: a test that shells out runs in a process this patch does not reach — the fixture
    regeneration and id-stability subprocesses are the current examples.
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded(name: str, real: Any) -> Any:
        def wrapper(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
            if not _is_local(self, address):
                raise OutboundNetworkError(
                    f"socket.{name}({address!r}) blocked: the test suite runs offline. "
                    "If a test genuinely needs a network peer, stand up a local one."
                )
            return real(self, address, *args, **kwargs)

        return wrapper

    socket.socket.connect = guarded("connect", real_connect)  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded("connect_ex", real_connect_ex)  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root, resolved from this file rather than the working directory."""
    return Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _clean_fixture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete SNAP_USE_FIXTURES from the environment before every test so a test
    that wants fixture mode must opt in explicitly. Prevents CI's job-level
    SNAP_USE_FIXTURES=1 from silently changing unit-test behaviour."""
    monkeypatch.delenv("SNAP_USE_FIXTURES", raising=False)
