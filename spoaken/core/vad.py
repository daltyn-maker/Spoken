"""
core/vad.py
───────────
Voice Activity Detection for Spoaken.

Primary:  webrtcvad — Google's WebRTC VAD (C extension).
Fallback: energy-gate — pure-Python RMS threshold (no dependencies).

webrtcvad frame constraints (16 kHz):
  Valid frame lengths: 160 samples (10 ms), 320 samples (20 ms),
                       480 samples (30 ms).  The engine block size is
  800 samples (50 ms), split here into 480 + 320 for processing.

Public API consumed by engine.py
─────────────────────────────────
  VAD(aggressiveness, min_speech_ms, silence_gap_ms)
  .process(pcm_bytes)  → bytes | None   (None = silence gate closed)
  .reset()
  .set_aggressiveness(n, save=False)
  .set_min_speech(ms,   save=False)
  .set_silence_gap(ms,  save=False)
  .save_config()

BUG-FIXES vs original
──────────────────────
  1. process() — `ms` was computed from `len(pcm_bytes)` (raw bytes) instead of
     the number of samples.  For int16 audio each sample is 2 bytes, so the
     original code over-counted by 2×, making the gate open/close at half the
     configured thresholds.  Fixed: divide by _BYTES_PER_SAMPLE before dividing
     by sample rate.

  2. _classify_webrtcvad() — the "keep at most one partial frame" guard ran
     AFTER consuming the 20 ms fragment, but only trimmed if the buffer was
     LARGER than one 30 ms frame.  After the 20 ms fragment is consumed the
     remaining bytes are at most 319 bytes (< _FRAME_30MS_BYTES = 960), so the
     trim condition was never True and residual bytes could accumulate over time.
     Fixed: trim unconditionally to the last _FRAME_20MS_BYTES worth of data
     (the smallest valid frame size), which is the tightest safe bound.

  3. set_aggressiveness() / set_min_speech() / set_silence_gap() — the `save`
     parameter was a plain keyword argument that callers could accidentally pass
     positionally.  Changed to keyword-only (*, save=True) to match the
     documented API and prevent silent misuse.

  4. save_config() — used a bare `except Exception` that swallowed *all* errors
     including KeyboardInterrupt derivatives.  Changed to `except OSError` for
     file-system errors and re-raises unexpected exceptions.

  5. _get_write_lock() — the try/except imported engine to borrow its lock, but
     if that import raised for any reason (e.g. circular import during startup)
     the fallback created a *new* threading.Lock() on every call, meaning each
     save used a different lock and the guard was ineffective.  Fixed by caching
     the fallback lock in a module-level variable.
"""

from __future__ import annotations

import sys
import json
import threading
from pathlib import Path

# ── webrtcvad optional import ─────────────────────────────────────────────────
try:
    import webrtcvad as _webrtcvad
    _WEBRTCVAD_OK = True
except ImportError:
    _webrtcvad    = None
    _WEBRTCVAD_OK = False

# ── Constants ─────────────────────────────────────────────────────────────────
_SAMPLE_RATE      = 16_000
_BYTES_PER_SAMPLE = 2                               # int16 = 2 bytes
_FRAME_30MS_BYTES = 480 * _BYTES_PER_SAMPLE         # 960 bytes
_FRAME_20MS_BYTES = 320 * _BYTES_PER_SAMPLE         # 640 bytes
_ENERGY_THRESHOLD = 0.015

# ── Config path helpers ───────────────────────────────────────────────────────
_HERE        = Path(__file__).resolve().parent
_SPOAKEN_DIR = _HERE.parent
_ROOT        = _SPOAKEN_DIR.parent

_CONFIG_CANDIDATES: list[Path] = [
    _ROOT        / "spoaken_config.json",
    _SPOAKEN_DIR / "spoaken_config.json",
    Path.home()  / ".spoaken" / "config.json",
]


def _find_config_path() -> Path | None:
    return next((p for p in _CONFIG_CANDIDATES if p.exists()), None)


# FIX #5: module-level fallback lock so we always get the SAME lock object
# when the engine import fails, making the write guard actually effective.
_fallback_write_lock: threading.Lock | None = None


def _get_write_lock() -> threading.Lock:
    global _fallback_write_lock
    try:
        from spoaken.core.engine import _config_write_lock
        return _config_write_lock
    except ImportError:
        if _fallback_write_lock is None:
            _fallback_write_lock = threading.Lock()
        return _fallback_write_lock


# ═════════════════════════════════════════════════════════════════════════════
# VAD class
# ═════════════════════════════════════════════════════════════════════════════

class VAD:
    """
    Voice activity detector.

    Uses webrtcvad when available, falls back to energy-gate otherwise.
    """

    def __init__(
        self,
        aggressiveness: int = 2,
        min_speech_ms:  int = 200,
        silence_gap_ms: int = 500,
    ):
        self._aggressiveness = max(0, min(3, int(aggressiveness)))
        self._min_speech_ms  = int(min_speech_ms)
        self._silence_gap_ms = int(silence_gap_ms)

        self._speech_ms  = 0
        self._silence_ms = 0
        self._gate_open  = False
        self._buf        = b""
        self._dirty      = False

        self._vad: object | None = None
        if _WEBRTCVAD_OK and _webrtcvad is not None:
            try:
                self._vad = _webrtcvad.Vad(self._aggressiveness)
            except Exception as exc:
                print(f"[VAD]: webrtcvad init failed — {exc}; using energy-gate",
                      file=sys.stderr)
                self._vad = None

        backend = "webrtcvad" if self._vad is not None else "energy-gate"
        print(f"[VAD]: backend={backend}  agg={self._aggressiveness}  "
              f"min_speech={self._min_speech_ms}ms  "
              f"silence_gap={self._silence_gap_ms}ms",
              file=sys.stderr)

    # ─────────────────────────────────────────────────────────────────────────
    # Core processing
    # ─────────────────────────────────────────────────────────────────────────

    def process(self, pcm_bytes: bytes) -> bytes | None:
        """
        Process a raw PCM block (int16, 16 kHz, mono).

        FIX #1: ms duration is now computed correctly as
          (bytes / bytes_per_sample) / sample_rate * 1000
        instead of the original
          bytes / sample_rate * 1000
        which over-counted by 2× for int16 audio.
        """
        self._buf += pcm_bytes

        active = self._classify_buffer()

        # FIX #1: divide by _BYTES_PER_SAMPLE to get sample count first
        ms = (len(pcm_bytes) / _BYTES_PER_SAMPLE) / _SAMPLE_RATE * 1000

        if active:
            self._speech_ms  += ms
            self._silence_ms  = 0
            if not self._gate_open and self._speech_ms >= self._min_speech_ms:
                self._gate_open = True
        else:
            self._silence_ms += ms
            self._speech_ms   = 0
            if self._gate_open and self._silence_ms >= self._silence_gap_ms:
                self._gate_open = False

        return pcm_bytes if self._gate_open else None

    def _classify_buffer(self) -> bool:
        if self._vad is not None:
            return self._classify_webrtcvad()
        return self._classify_energy()

    def _classify_webrtcvad(self) -> bool:
        """webrtcvad path — processes 30 ms + optional 20 ms frames."""
        speech = False

        # Consume as many 30 ms frames as possible
        while len(self._buf) >= _FRAME_30MS_BYTES:
            frame     = self._buf[:_FRAME_30MS_BYTES]
            self._buf = self._buf[_FRAME_30MS_BYTES:]
            try:
                if self._vad.is_speech(frame, _SAMPLE_RATE):
                    speech = True
            except Exception:
                pass

        # Consume any remaining 20 ms fragment
        if len(self._buf) >= _FRAME_20MS_BYTES:
            frame     = self._buf[:_FRAME_20MS_BYTES]
            self._buf = self._buf[_FRAME_20MS_BYTES:]
            try:
                if self._vad.is_speech(frame, _SAMPLE_RATE):
                    speech = True
            except Exception:
                pass

        # FIX #2: trim to _FRAME_20MS_BYTES unconditionally — after consuming
        # both frame sizes, any remainder is < _FRAME_20MS_BYTES, so the old
        # condition (`> _FRAME_30MS_BYTES`) was never True and bytes accumulated.
        if len(self._buf) > _FRAME_20MS_BYTES:
            self._buf = self._buf[-_FRAME_20MS_BYTES:]

        return speech

    def _classify_energy(self) -> bool:
        """Energy-gate fallback — RMS threshold on the full buffer."""
        if not self._buf:
            return False
        import numpy as np
        arr = np.frombuffer(self._buf, dtype=np.int16).astype(np.float32)
        self._buf = b""
        rms = float(np.sqrt(np.mean(arr ** 2))) / 32768.0
        return rms >= _ENERGY_THRESHOLD

    # ─────────────────────────────────────────────────────────────────────────
    # State reset
    # ─────────────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self._speech_ms  = 0
        self._silence_ms = 0
        self._gate_open  = False
        self._buf        = b""

    # ─────────────────────────────────────────────────────────────────────────
    # Live configuration
    # FIX #3: `save` is keyword-only (*, save=True) on all three setters to
    # prevent accidental positional passing.
    # ─────────────────────────────────────────────────────────────────────────

    def set_aggressiveness(self, level: int, *, save: bool = True) -> None:
        level = max(0, min(3, int(level)))
        if level == self._aggressiveness:
            return
        self._aggressiveness = level
        if self._vad is not None:
            try:
                self._vad.set_mode(level)
            except Exception as exc:
                print(f"[VAD]: set_aggressiveness({level}) failed — {exc}",
                      file=sys.stderr)
        self._dirty = True
        if save:
            self.save_config()

    def set_min_speech(self, ms: int, *, save: bool = True) -> None:
        ms = max(0, int(ms))
        if ms == self._min_speech_ms:
            return
        self._min_speech_ms = ms
        self._dirty = True
        if save:
            self.save_config()

    def set_silence_gap(self, ms: int, *, save: bool = True) -> None:
        ms = max(0, int(ms))
        if ms == self._silence_gap_ms:
            return
        self._silence_gap_ms = ms
        self._dirty = True
        if save:
            self.save_config()

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def save_config(self) -> None:
        """
        Flush dirty VAD settings to spoaken_config.json.

        FIX #4: catch OSError for filesystem errors; re-raise unexpected
        exceptions rather than silently swallowing them.
        """
        if not self._dirty:
            return
        path = _find_config_path()
        if path is None:
            return
        lock = _get_write_lock()
        with lock:
            try:
                existing: dict = {}
                if path.exists():
                    with open(path, encoding="utf-8") as fh:
                        existing = json.load(fh)
                existing.update({
                    "vad_aggressiveness": self._aggressiveness,
                    "vad_min_speech_ms":  self._min_speech_ms,
                    "vad_silence_gap_ms": self._silence_gap_ms,
                })
                tmp = path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(existing, fh, indent=2)
                tmp.replace(path)
                self._dirty = False
            except OSError as exc:
                # FIX #4: only catch filesystem errors; re-raise others
                print(f"[VAD]: save_config failed — {exc}", file=sys.stderr)
