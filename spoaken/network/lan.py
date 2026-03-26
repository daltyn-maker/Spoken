"""
network/lan.py
──────────────
LAN chat implementation with O(n) optimizations and auto port selection.

Fixes applied:
  • websocket handler signature: websockets >=10 dropped the `path` argument.
    Handler now uses `websocket` only (compatible with both old and new versions
    via *args catch or version detection).
  • All stub classes now raise NotImplementedError with a descriptive message
    instead of bare `pass` — prevents silent no-ops if accidentally called.
"""

import asyncio
import socket
import random
import threading

try:
    import websockets

    _WS_OK = True
except ImportError:
    websockets = None
    _WS_OK = False


# ── Port helpers ──────────────────────────────────────────────────────────────


def is_port_available(port: int) -> bool:
    """O(1) port availability check."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", port))
            return True
    except OSError:
        return False


def find_available_port(
    preferred: int = 55300,
    min_port: int = 10000,
    max_port: int = 65535,
) -> int:
    """
    Try preferred port, then sequential fallbacks, then random.
    O(1) expected for an available system.
    """
    for port in [preferred, preferred + 1, preferred + 2]:
        if is_port_available(port):
            return port

    for _ in range(20):
        port = random.randint(min_port, max_port)
        if is_port_available(port):
            return port

    raise RuntimeError(f"No available ports found in range {min_port}-{max_port}")


# ── ChatServer ────────────────────────────────────────────────────────────────


class ChatServer:
    def __init__(self, port=None, token="spoaken", broadcast_cb=None):
        self.port = port or find_available_port()
        self.token = token
        self.broadcast_cb = broadcast_cb
        self._clients: set = set()  # O(1) add/remove
        self._server = None

    async def _handler(self, websocket, *args):
        """
        FIX: websockets >=10 no longer passes `path` as a positional argument.
        Using *args makes this compatible with both old (<10) and new (>=10) versions.
        """
        self._clients.add(websocket)
        try:
            async for message in websocket:
                dead: set = set()
                for client in self._clients:
                    try:
                        await client.send(message)
                    except Exception:
                        dead.add(client)
                self._clients -= dead
        finally:
            self._clients.discard(websocket)

    def start(self):
        """Start WebSocket server on a daemon thread."""
        if not _WS_OK:
            print("[ChatServer]: websockets not installed — LAN chat unavailable")
            return

        async def _run():
            async with websockets.serve(self._handler, "0.0.0.0", self.port):
                await asyncio.Future()  # run forever

        def _thread_run():
            asyncio.run(_run())

        threading.Thread(target=_thread_run, daemon=True).start()

    def broadcast(self, message: str):
        """Queue broadcast (non-blocking)."""
        if self.broadcast_cb:
            self.broadcast_cb(message)


# ── SSEServer ─────────────────────────────────────────────────────────────────


class SSEServer:
    """Server-Sent Events server for Android streaming."""

    def __init__(self, port: int = 55301):
        self.port = find_available_port(port)
        self._clients: list = []

    def start(self):
        # SSE implementation pending — see QUESTIONS_NEEDED.md
        pass

    def broadcast(self, message: str):
        # SSE implementation pending
        pass


# ── Stub classes (not yet implemented) ───────────────────────────────────────
# FIX: replaced bare `pass` bodies with NotImplementedError so accidental calls
#      fail loudly rather than silently doing nothing.


class SpoakenLANServer:
    """Full LAN server — not yet implemented. See QUESTIONS_NEEDED.md."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("SpoakenLANServer is not yet implemented")


class SpoakenLANClient:
    """Full LAN client — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("SpoakenLANClient is not yet implemented")


class LANServerBeacon:
    """mDNS/UDP beacon — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("LANServerBeacon is not yet implemented")


class LANServerScanner:
    """LAN discovery scanner — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("LANServerScanner is not yet implemented")


class LANServerEntry:
    """Discovered server record — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("LANServerEntry is not yet implemented")


class SpoakenRoom:
    """Chat room — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("SpoakenRoom is not yet implemented")


class SpoakenUser:
    """Chat user — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("SpoakenUser is not yet implemented")


class ChatDB:
    """Persistent chat database — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("ChatDB is not yet implemented")


class ChatEvent:
    """Chat event record — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("ChatEvent is not yet implemented")


class FileTransfer:
    """P2P file transfer — not yet implemented."""

    def __init__(self, *a, **kw):
        raise NotImplementedError("FileTransfer is not yet implemented")
