"""
system/session_recovery.py
───────────────────────────
Periodic transcript auto-save with crash-recovery support.

Saves data_store to ~/.spoaken/session_recovery.json every 60 seconds
during an active recording session.  On the next launch, if the file
exists and is less than 24 hours old, the controller offers to restore
the segments into the transcript.

The recovery file is always deleted on a clean session end (stop
recording or close window).  It only persists when the process is
killed unexpectedly.

Changes from v2 (tmp cleanup)
──────────────────────────────
  • _save() now guarantees the .tmp staging file is removed even when
    os.replace() fails (e.g. cross-device rename on some Linux mounts).
    Previously a failed replace left an orphaned .tmp that would never
    be cleaned up until the next successful save.

Changes from v1 (pickle → JSON)
────────────────────────────────
  • Storage format changed from pickle (.pkl) to JSON (.json).
  • Old .pkl file is silently migrated and deleted on first load.
  • _save() is protected by a threading.Lock.

Public API
──────────
  SessionRecovery(controller, interval_s=60)
  .start()                     Begin auto-save loop
  .stop()                      Stop loop and delete recovery file (clean exit)
  .check_restore()             Return saved segments list or None
  .discard()                   Delete recovery file without restoring
  .recovery_file_age_minutes() Return age of recovery file in minutes or None
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

_RECOVERY_PATH     = Path.home() / ".spoaken" / "session_recovery.json"
_RECOVERY_PATH_OLD = Path.home() / ".spoaken" / "session_recovery.pkl"  # legacy
_RECOVERY_MAX_AGE_H = 24   # hours — older files are auto-discarded


class SessionRecovery:
    """
    Periodic transcript auto-save with crash-recovery support.

    Parameters
    ----------
    controller  : TranscriptionController instance — used to read data_store.
    interval_s  : Seconds between auto-saves (default 60).
    """

    def __init__(self, controller, interval_s: int = 60):
        self._ctrl     = controller
        self._interval = interval_s
        self._running  = False
        self._thread: Optional[threading.Thread] = None
        self._save_lock = threading.Lock()   # prevents concurrent write corruption

        # Silently migrate old pickle file on first instantiation
        self._migrate_legacy()

    # ── Legacy migration ──────────────────────────────────────────────────────

    def _migrate_legacy(self):
        """
        If a .pkl recovery file exists from a prior install, attempt to load
        it, re-save as JSON, and delete the .pkl.  Silently ignored on failure.
        """
        if not _RECOVERY_PATH_OLD.exists():
            return
        try:
            import pickle
            with open(_RECOVERY_PATH_OLD, "rb") as f:
                data = pickle.load(f)
            # Validate structure before trusting it
            if isinstance(data, dict) and "segments" in data and "ts" in data:
                _RECOVERY_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(_RECOVERY_PATH, "w", encoding="utf-8") as f:
                    json.dump(
                        {"ts": data["ts"], "segments": list(data["segments"])},
                        f, indent=2,
                    )
        except Exception:
            pass
        finally:
            try:
                _RECOVERY_PATH_OLD.unlink(missing_ok=True)
            except Exception:
                pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        """Begin the auto-save background thread."""
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop auto-save and delete the recovery file (clean exit path)."""
        self._running = False
        self.discard()

    # ── Auto-save loop ────────────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            time.sleep(self._interval)
            if not self._running:
                break
            self._save()

    def _save(self):
        """
        Write a JSON snapshot of the current data_store to the recovery file.
        Protected by a lock so concurrent start()/stop() races cannot corrupt
        a write in progress.

        The .tmp staging file is always cleaned up — even when os.replace()
        fails (e.g. cross-device rename on some Linux mounts).  Without the
        finally block a failed replace leaves an orphaned .tmp that is never
        removed until the next successful save.
        """
        try:
            if not self._ctrl.model:
                return
            segments = list(self._ctrl.model.data_store)
            if not segments:
                return   # nothing to save — don't create a spurious file

            payload = {"ts": time.time(), "segments": segments}

            with self._save_lock:
                _RECOVERY_PATH.parent.mkdir(parents=True, exist_ok=True)
                # Write to a temp file then rename — atomic on POSIX.
                # The finally block guarantees .tmp removal on any failure.
                tmp = _RECOVERY_PATH.with_suffix(".tmp")
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2)
                    os.replace(tmp, _RECOVERY_PATH)
                finally:
                    # Silently remove stale staging file if replace failed.
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass

        except Exception:
            pass   # never raise from a background thread

    # ── Restore API ───────────────────────────────────────────────────────────

    def check_restore(self) -> Optional[list[str]]:
        """
        Return saved segments if a recent recovery file exists, else None.

        Returns None if:
          • the file does not exist
          • it is unreadable or corrupt
          • it is older than _RECOVERY_MAX_AGE_H hours
        """
        try:
            if not _RECOVERY_PATH.exists():
                return None
            with open(_RECOVERY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "ts" not in data or "segments" not in data:
                self.discard()
                return None
            age_h = (time.time() - float(data["ts"])) / 3600
            if age_h > _RECOVERY_MAX_AGE_H:
                self.discard()
                return None
            segments = [s for s in data["segments"] if isinstance(s, str) and s.strip()]
            return segments if segments else None
        except Exception:
            # Corrupt or unreadable — discard and start fresh
            self.discard()
            return None

    def discard(self):
        """Delete the recovery file without restoring."""
        try:
            _RECOVERY_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    def recovery_file_age_minutes(self) -> Optional[float]:
        """Return the age of the recovery file in minutes, or None if absent."""
        try:
            if not _RECOVERY_PATH.exists():
                return None
            with open(_RECOVERY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (time.time() - float(data["ts"])) / 60
        except Exception:
            return None
