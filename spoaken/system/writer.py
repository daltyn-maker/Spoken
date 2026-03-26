"""
processing/writer.py
────────────────────
DirectWindowWriter — types transcribed text into the focused window.

KEY FIX
───────
pyautogui (and its mouseinfo dependency) must NEVER be imported at module
level on Linux.  mouseinfo calls Xlib.Display() at import time, which
requires a live, authorised X11 connection.  When Spoaken starts in a
background thread this raises:

    Xlib.error.DisplayConnectionError: Can't connect to display ":0":
        Authorization required, but no authorization protocol specified

The fix is a lazy import: pyautogui is imported inside each method that
actually needs it, so the Xlib connection is only attempted when the user
explicitly triggers a window-write action, by which time the display is
always available.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Optional


def _lazy_pyautogui():
    """Import pyautogui on demand — never at module level."""
    try:
        import pyautogui
        return pyautogui
    except ImportError as e:
        raise ImportError(
            "pyautogui is not installed. Run: pip install pyautogui"
        ) from e


class DirectWindowWriter:
    """
    Types transcribed text directly into the currently focused window.

    pyautogui is imported lazily (on first write) so that importing this
    module never triggers an Xlib / X11 connection.
    """

    def __init__(self, title: str = "", log_cb=None):
        self._title   = title
        self._log_cb  = log_cb or (lambda m: print(m, file=sys.stderr))
        self._lock    = threading.Lock()
        self._last_write: float = 0.0
        self._min_interval: float = 0.05
        self._enabled: bool = True
        self._pyautogui = None   # populated on first use

    def _get_pag(self):
        if self._pyautogui is None:
            self._pyautogui = _lazy_pyautogui()
        return self._pyautogui

    def refresh(self, title: str):
        """Update the target window title."""
        self._title = title

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = bool(value)

    def write(self, text: str, interval: float = 0.02) -> bool:
        if not self._enabled or not text:
            return False
        now = time.monotonic()
        with self._lock:
            if (now - self._last_write) < self._min_interval:
                time.sleep(self._min_interval - (now - self._last_write))
            try:
                pag = self._get_pag()
                pag.typewrite(text, interval=interval)
                self._last_write = time.monotonic()
                return True
            except Exception as exc:
                self._log_cb(f"[Writer Error]: {exc}")
                return False

    def write_key(self, key: str) -> bool:
        if not self._enabled:
            return False
        try:
            self._get_pag().press(key)
            return True
        except Exception as exc:
            self._log_cb(f"[Writer Error]: {exc}")
            return False

    def hotkey(self, *keys: str) -> bool:
        if not self._enabled:
            return False
        try:
            self._get_pag().hotkey(*keys)
            return True
        except Exception as exc:
            self._log_cb(f"[Writer Error]: {exc}")
            return False

    def is_available(self) -> bool:
        """Non-raising probe — True if pyautogui can connect to the display."""
        try:
            self._get_pag()
            return True
        except Exception:
            return False
