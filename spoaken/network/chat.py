"""
network/chat.py
───────────────
Compatibility layer that re-exports the chat classes used by the control layer.

  ChatServer          — LAN WebSocket server
  SSEServer           — HTTP Server-Sent Events server for Android / browser
  SpoakenLANServer    — full LAN server (room management, file transfer, auth)
  SpoakenLANClient    — LAN client (connect to a LAN server)
  SpoakenOnlineRelay  — Tor P2P relay server  (None if online.py not installed)
  SpoakenOnlineClient — Tor P2P client        (None if online.py not installed)

online.py is optional — it is only installed when the user selects Tor P2P
during setup.  If it is absent (or later deleted), this module degrades
gracefully: the online classes are set to None and the rest of Spoaken is
completely unaffected.  gui.py already guards _P2P_AVAILABLE via find_spec,
so the UI P2P button will be disabled automatically.
"""

# ── LAN chat (local network — always available) ───────────────────────────────
from spoaken.network.lan import (
    ChatServer,
    SSEServer,
    SpoakenLANServer,
    SpoakenLANClient,
    LANServerBeacon,
    LANServerScanner,
    LANServerEntry,
    SpoakenRoom,
    SpoakenUser,
    ChatDB,
    ChatEvent,
    FileTransfer,
)

# ── Online Tor P2P chat (optional — only present if user selected it) ─────────
# If online.py is missing or deleted, all P2P symbols are set to None so no
# other file in the codebase can accidentally trigger an ImportError.
try:
    from spoaken.network.online import (
        SpoakenOnlineRelay,
        SpoakenOnlineClient,
        OnlineRoom,
        OnlineUser,
        FileRelay,
    )
    _P2P_INSTALLED = True
except ModuleNotFoundError:
    # online.py was not installed (offline install or Tor P2P not selected).
    # Set symbols to None so callers can do:  if SpoakenOnlineRelay is not None
    SpoakenOnlineRelay  = None
    SpoakenOnlineClient = None
    OnlineRoom          = None
    OnlineUser          = None
    FileRelay           = None
    _P2P_INSTALLED      = False
except ImportError as _imp_err:
    # online.py exists but a dependency (stem, PySocks, aiohttp) is missing.
    import sys as _sys
    print(
        f"[chat.py]: Tor P2P dependency missing — {_imp_err}\n"
        "  Install with: python install.py --online-only",
        file=_sys.stderr,
    )
    SpoakenOnlineRelay  = None
    SpoakenOnlineClient = None
    OnlineRoom          = None
    OnlineUser          = None
    FileRelay           = None
    _P2P_INSTALLED      = False

__all__ = [
    # LAN
    "ChatServer",
    "SSEServer",
    "SpoakenLANServer",
    "SpoakenLANClient",
    "LANServerBeacon",
    "LANServerScanner",
    "LANServerEntry",
    "SpoakenRoom",
    "SpoakenUser",
    "ChatDB",
    "ChatEvent",
    "FileTransfer",
    # Online Tor P2P (None when not installed)
    "SpoakenOnlineRelay",
    "SpoakenOnlineClient",
    "OnlineRoom",
    "OnlineUser",
    "FileRelay",
    # Feature flag
    "_P2P_INSTALLED",
]
