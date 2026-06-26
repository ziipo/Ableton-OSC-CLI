"""Low-level OSC transport for talking to AbletonOSC.

Sends messages to Live's listening port (11000) and, for queries, blocks on a
reply received on the response port (11001). AbletonOSC replies to the same
address it was sent, so we match on address to resolve the right response.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, List, Optional, Tuple

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SEND_PORT = 11000
DEFAULT_RECV_PORT = 11001


class AbletonOSCError(RuntimeError):
    """Raised when AbletonOSC reports an error or a query times out."""


class OSCClient:
    """A synchronous request/response client for AbletonOSC.

    The receiving server runs on a background thread. ``query`` sends a message
    and waits for the matching reply; ``send`` is fire-and-forget.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        recv_port: int = DEFAULT_RECV_PORT,
        timeout: float = 2.0,
    ) -> None:
        self.host = host
        self.send_port = send_port
        self.recv_port = recv_port
        self.timeout = timeout

        self._client = SimpleUDPClient(host, send_port)

        # Per-address queues so concurrent waiters don't steal each other's replies.
        self._queues: dict[str, "queue.Queue[Tuple[Any, ...]]"] = {}
        self._lock = threading.Lock()

        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._on_message)
        self._server = ThreadingOSCUDPServer((host, recv_port), dispatcher)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()

    def _on_message(self, address: str, *args: Any) -> None:
        with self._lock:
            q = self._queues.get(address)
            if q is None:
                q = queue.Queue()
                self._queues[address] = q
        q.put(args)

    def send(self, address: str, *args: Any) -> None:
        """Fire-and-forget: send an OSC message, expecting no reply."""
        self._client.send_message(address, list(args))

    def query(
        self, address: str, *args: Any, timeout: Optional[float] = None
    ) -> Tuple[Any, ...]:
        """Send a message and block for the reply on the same address.

        Returns the reply argument tuple. Raises ``AbletonOSCError`` on timeout
        or if AbletonOSC sends an ``/live/error`` message.
        """
        timeout = self.timeout if timeout is None else timeout

        with self._lock:
            q = self._queues.setdefault(address, queue.Queue())
            err_q = self._queues.setdefault("/live/error", queue.Queue())
            # Drain stale entries so we read a fresh reply.
            _drain(q)
            _drain(err_q)

        self._client.send_message(address, list(args))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return q.get(timeout=0.02)
            except queue.Empty:
                pass
            try:
                err = err_q.get_nowait()
                raise AbletonOSCError(f"AbletonOSC error: {err}")
            except queue.Empty:
                pass
        raise AbletonOSCError(
            f"Timed out after {timeout}s waiting for reply to {address}. "
            "Is Ableton running with the AbletonOSC control surface enabled?"
        )

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _drain(q: "queue.Queue[Any]") -> None:
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        pass
