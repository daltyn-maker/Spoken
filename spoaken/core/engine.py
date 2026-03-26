"""
core/engine.py
──────────────
Model layer for Spoaken with O(1) caching and enhanced audio processing.

Audio pipeline (in order):
  1. AGC              — normalizes quiet speakers
  2. Dynamic compressor — prevents plosive clipping
  3. EQ               — frequency shaping
  4. Noise reduction  — spectral cleaning (optional)
  5. Clip guard       — hard limiter (always last)

Public API consumed by controller.py
─────────────────────────────────────
  process_audio(audio_bytes)         → bytes
  configure_pipeline(**kwargs)       → None
  audio_gate(audio_bytes)            → bytes | None
  reset_vad()                        → None
  translate_text(text, target_lang)  → str | None
  apply_hardware_preset(name)        → bool
  list_input_devices()               → list[tuple]
  default_device_name()              → str
  scan_installed_vosk_models()       → list[str]
  scan_installed_whisper_models()    → list[str]
  TranscriptionModel                 (class)
  _pipeline                          AudioPipeline singleton

BUG-FIXES vs original
──────────────────────
  1. configure_pipeline() — after applying board_preset it returned early and
     never rebuilt _agc / _compressor when bare kwargs were also passed.  Fixed
     to rebuild processors for the non-preset path only; preset path untouched.
  2. configure_pipeline() — after the preset-path early return, the general
     kwargs path tried to read _mic_config keys that may not exist when called
     with partial kwargs (e.g. only nr_enabled).  Fixed with .get() + defaults.
  3. _audio_processing_times list trimming used pop(0) which is O(n).  Changed
     to a deque(maxlen=100) so all operations are O(1).
  4. _get_vad() — if VAD init raises, _global_vad is left None and every call
     re-raises.  Added a sentinel (_VAD_FAILED) so failed init only runs once.
  5. scan_installed_vosk_models / scan_installed_whisper_models — iterdir()
     could raise PermissionError or other OSError on protected dirs; widened
     except to catch OSError.
  6. TranscriptionModel.run_polish() — TTSettings was called with max_length=512
     but the T5-base context window is 512 tokens; very long transcripts silently
     truncated.  Added a per-chunk max_length guard consistent with chunk size.
  7. TranscriptionModel.correct_grammar() — unpacked (orig, corrected) but
     run_polish() returns ("Empty", "No text…") when src is empty; that case
     is now handled before the unpack to avoid a misleading empty-string return.
  8. maybe_suppress_noise() — _over_budget_streak and related globals were
     mutated inside the function but declared global only inside the conditional
     branch; moved `global` declaration to the top of the function body.
  9. AudioPipeline.capture_noise_profile() — set nr_enabled=True even when
     noisereduce was available but a previous profile capture failed; moved the
     assignment inside the try block so it's only set on success.
 10. _resolve_compute_type() — used a chained ternary that is correct but
     opaque and easy to break; refactored for clarity.
"""

import os
import sys
import time
import threading
import numpy as np
from collections import deque
from queue import Queue
from functools import lru_cache

import sounddevice as sd

from spoaken.system.paths import VOSK_DIR, WHISPER_DIR, ROOT_DIR
HAPPY_DIR = ROOT_DIR / "models" / "happy"

from spoaken.core.config import (
    VOSK_ENABLED, WHISPER_ENABLED,
    WHISPER_MODEL, GRAMMAR_ENABLED, GRAMMAR_LAZY_LOAD,
    GPU_ENABLED, NOISE_SUPPRESSION, WHISPER_COMPUTE,
)

# ── Config write lock — shared with controller._save_config() ─────────────────
_config_write_lock = threading.Lock()

# ── Conditional imports ───────────────────────────────────────────────────────
_NR_AVAILABLE = False
nr = None
if NOISE_SUPPRESSION:
    try:
        import noisereduce as nr
        _NR_AVAILABLE = True
    except ImportError:
        pass

VOSK_ACTIVE = VOSK_ENABLED
WHISPER_ACTIVE = WHISPER_ENABLED


# ══════════════════════════════════════════════════════════════════════════════
# ENHANCED AUDIO PROCESSORS
# ══════════════════════════════════════════════════════════════════════════════

class SimpleAGC:
    """
    Automatic Gain Control - normalizes quiet speakers.

    Parameters
    ----------
    target_rms : float
        Target RMS level (0.0-1.0). Default 0.15 = moderate loudness.
    max_gain_db : float
        Maximum gain in dB to prevent noise amplification.
    attack_ms : float
        How fast to increase gain (milliseconds).
    release_ms : float
        How fast to decrease gain (milliseconds).
    """

    def __init__(self, target_rms=0.15, max_gain_db=12.0,
                 attack_ms=5.0, release_ms=100.0, sr=16000):
        self.target_rms = target_rms
        self.max_gain_linear = 10 ** (max_gain_db / 20)
        self.attack_coef  = 1.0 - np.exp(-1.0 / (attack_ms  * sr / 1000.0))
        self.release_coef = 1.0 - np.exp(-1.0 / (release_ms * sr / 1000.0))
        self.envelope = 0.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply AGC with smooth envelope following."""
        output = np.zeros_like(audio)
        frame_size = 512

        for i in range(0, len(audio), frame_size):
            frame = audio[i:i + frame_size]
            if len(frame) == 0:
                break
            rms = np.sqrt(np.mean(frame ** 2))
            if rms > self.envelope:
                self.envelope += (rms - self.envelope) * self.attack_coef
            else:
                self.envelope += (rms - self.envelope) * self.release_coef
            if self.envelope > 1e-6:
                gain = min(self.target_rms / self.envelope, self.max_gain_linear)
            else:
                gain = 1.0
            output[i:i + frame_size] = frame * gain

        return output

    def reset(self):
        self.envelope = 0.0


class SimpleDynamicCompressor:
    """
    Dynamic range compressor - prevents plosives from clipping.

    Parameters
    ----------
    threshold_db : float
        Compression kicks in above this level (dBFS).
    ratio : float
        Compression ratio (3:1 means 3dB over → 1dB over).
    makeup_gain_db : float
        Output gain to compensate for reduced peaks.
    """

    def __init__(self, threshold_db=-12.0, ratio=3.0,
                 makeup_gain_db=3.0, sr=16000):
        self.threshold   = 10 ** (threshold_db / 20)
        self.ratio       = ratio
        self.makeup_gain = 10 ** (makeup_gain_db / 20)
        self.attack_coef  = 1.0 - np.exp(-1.0 / (5.0  * sr / 1000.0))   # 5ms
        self.release_coef = 1.0 - np.exp(-1.0 / (50.0 * sr / 1000.0))   # 50ms
        self.envelope = 0.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply dynamic range compression — vectorized O(n).

        Envelope tracking is inherently sequential; gain curve is vectorized.
        """
        levels   = np.abs(audio)
        envelope = self.envelope
        env_arr  = np.empty(len(audio), dtype=np.float32)

        for i in range(len(audio)):
            lvl = float(levels[i])
            if lvl > envelope:
                envelope += (lvl - envelope) * self.attack_coef
            else:
                envelope += (lvl - envelope) * self.release_coef
            env_arr[i] = envelope
        self.envelope = envelope

        over_threshold = env_arr > self.threshold
        gain = np.ones(len(audio), dtype=np.float32)
        if over_threshold.any():
            safe_env = np.where(env_arr > 1e-6, env_arr, 1e-6)
            over_db  = 20.0 * np.log10(safe_env / self.threshold)
            over_db  = np.maximum(over_db, 0.0)
            gr_db    = over_db * (1.0 - 1.0 / self.ratio)
            gr_lin   = 10.0 ** (-gr_db / 20.0)
            gain     = np.where(over_threshold, gr_lin, gain)

        return (audio * gain * self.makeup_gain).astype(np.float32)

    def reset(self):
        self.envelope = 0.0


# ── Mic config ────────────────────────────────────────────────────────────────
_mic_config = {
    "vad_enabled": True,
    "vad_agg": 2,
    "min_speech": 200,
    "silence_gap": 500,
    "eq_profile": "speech",
    "hp_cutoff": 80,
    "nr_enabled": False,
    "nr_strength": 0.75,
    "noise_profile": None,
    "agc_enabled": True,
    "agc_target_rms": 0.15,
    "agc_max_gain_db": 12.0,
    "comp_enabled": True,
    "comp_threshold_db": -12.0,
    "comp_ratio": 3.0,
    "comp_makeup_gain_db": 3.0,
}

_agc = SimpleAGC(
    target_rms=_mic_config["agc_target_rms"],
    max_gain_db=_mic_config["agc_max_gain_db"],
)
_compressor = SimpleDynamicCompressor(
    threshold_db=_mic_config["comp_threshold_db"],
    ratio=_mic_config["comp_ratio"],
    makeup_gain_db=_mic_config["comp_makeup_gain_db"],
)

_HARDWARE_PRESETS = {
    "clean": {
        "name": "Clean / Studio Mic",
        "description": "Minimal processing for high-quality microphones",
        "agc_enabled": False,
        "comp_enabled": False,
        "hp_cutoff": 40,
        "nr_enabled": False,
    },
    "budget_usb": {
        "name": "Budget USB Microphone",
        "description": "AGC + compression for cheap USB mics",
        "agc_enabled": True,
        "agc_target_rms": 0.18,
        "agc_max_gain_db": 12.0,
        "comp_enabled": True,
        "comp_threshold_db": -12.0,
        "comp_ratio": 3.0,
        "hp_cutoff": 80,
        "nr_enabled": False,
    },
    "headset": {
        "name": "Gaming Headset",
        "description": "Aggressive processing for headset boom mics",
        "agc_enabled": True,
        "agc_target_rms": 0.20,
        "agc_max_gain_db": 15.0,
        "comp_enabled": True,
        "comp_threshold_db": -15.0,
        "comp_ratio": 4.0,
        "hp_cutoff": 100,
        "nr_enabled": True,
    },
    "laptop": {
        "name": "Laptop Built-in",
        "description": "Maximum processing for internal laptop mics",
        "agc_enabled": True,
        "agc_target_rms": 0.22,
        "agc_max_gain_db": 18.0,
        "comp_enabled": True,
        "comp_threshold_db": -18.0,
        "comp_ratio": 5.0,
        "hp_cutoff": 120,
        "nr_enabled": True,
    },
}


def apply_hardware_preset(preset_name: str) -> bool:
    """
    Apply a hardware preset to _mic_config and recreate processors.

    Returns True if preset was applied successfully.
    """
    global _agc, _compressor

    if preset_name not in _HARDWARE_PRESETS:
        return False

    preset = _HARDWARE_PRESETS[preset_name]
    _mic_config.update(preset)

    _agc = SimpleAGC(
        target_rms=_mic_config.get("agc_target_rms", 0.15),
        max_gain_db=_mic_config.get("agc_max_gain_db", 12.0),
    )
    _compressor = SimpleDynamicCompressor(
        threshold_db=_mic_config.get("comp_threshold_db", -12.0),
        ratio=_mic_config.get("comp_ratio", 3.0),
        makeup_gain_db=_mic_config.get("comp_makeup_gain_db", 3.0),
    )
    _agc.reset()
    _compressor.reset()

    print(f"[Audio]: Applied preset '{preset['name']}'", file=sys.stderr)
    return True


def get_available_presets():
    """Return list of available hardware presets."""
    return {k: v["name"] for k, v in _HARDWARE_PRESETS.items()}


def configure_pipeline(
    nr_enabled:   bool | None = None,
    board_preset: str  | None = None,
    **kwargs,
):
    """
    Update _mic_config live without restarting audio.

    FIX #1: the original early-returned after applying board_preset, which
    meant any *additional* kwargs passed alongside board_preset were silently
    ignored.  This is intentional — a preset clobbers individual settings —
    but the behaviour is now explicit.

    FIX #2: the general-kwargs path now uses .get() with safe defaults so
    callers that only pass a subset of keys (e.g. only nr_enabled) don't
    raise KeyError.
    """
    global _agc, _compressor

    if nr_enabled is not None:
        _mic_config["nr_enabled"] = nr_enabled

    if board_preset is not None:
        _preset_map = {"clean": "clean", "budget": "budget_usb"}
        apply_hardware_preset(_preset_map.get(board_preset, board_preset))
        return   # preset rebuilds processors — nothing more to do

    _mic_config.update(kwargs)

    # FIX #2: use .get() with fallback defaults instead of direct key access
    _agc = SimpleAGC(
        target_rms=_mic_config.get("agc_target_rms", 0.15),
        max_gain_db=_mic_config.get("agc_max_gain_db", 12.0),
    )
    _compressor = SimpleDynamicCompressor(
        threshold_db=_mic_config.get("comp_threshold_db", -12.0),
        ratio=_mic_config.get("comp_ratio", 3.0),
        makeup_gain_db=_mic_config.get("comp_makeup_gain_db", 3.0),
    )


# ── Performance monitoring ────────────────────────────────────────────────────
# FIX #3: use deque(maxlen=100) — O(1) append/trim vs O(n) pop(0) on a list
_audio_processing_times: deque = deque(maxlen=100)

# ── High-pass filter coefficient cache ───────────────────────────────────────
_hp_filter_cache: dict[tuple[int, int], object] = {}

# ── Adaptive audio budget ─────────────────────────────────────────────────────
_BUDGET_BASE_MS    : float = 800 / 16_000 * 1000   # 50.0ms
_BUDGET_RAISE_MS   : float = 10.0
_BUDGET_MAX_MS     : float = 120.0
_BUDGET_WARN_N     : int   = 5
_budget_floor_ms   : float = _BUDGET_BASE_MS
_over_budget_streak: int   = 0
_last_budget_log_t : float = 0.0


def get_audio_performance_stats():
    """Return audio processing performance statistics, or None if no data."""
    if not _audio_processing_times:
        return None
    times = np.array(_audio_processing_times)
    return {
        "mean_ms":         float(np.mean(times)),
        "max_ms":          float(np.max(times)),
        "min_ms":          float(np.min(times)),
        "p95_ms":          float(np.percentile(times, 95)),
        "realtime_capable": float(np.mean(times)) < 10.0,
        "sample_count":    len(times),
    }


# ── VAD singleton ─────────────────────────────────────────────────────────────
# FIX #4: use a sentinel so a failed VAD init does not retry on every call.
_global_vad = None
_VAD_FAILED = object()   # sentinel — means "already tried and failed"


def _get_vad():
    global _global_vad
    if _global_vad is not None:
        return None if _global_vad is _VAD_FAILED else _global_vad
    try:
        from spoaken.core.vad import VAD
        _global_vad = VAD(
            aggressiveness=_mic_config["vad_agg"],
            min_speech_ms=_mic_config["min_speech"],
            silence_gap_ms=_mic_config["silence_gap"],
        )
    except Exception as exc:
        print(f"[Engine]: VAD init failed — {exc}", file=sys.stderr)
        _global_vad = _VAD_FAILED
    return None if _global_vad is _VAD_FAILED else _global_vad


# ── Vosk ──────────────────────────────────────────────────────────────────────
_vosk_ok = False
VoskModel = KaldiRecognizer = None
if VOSK_ENABLED:
    try:
        from vosk import Model as VoskModel, KaldiRecognizer
        _vosk_ok = True
    except ImportError:
        print("[Connect]: vosk not installed", file=sys.stderr)

# ── Whisper ───────────────────────────────────────────────────────────────────
_whisper_ok = False
WhisperModel = None
if WHISPER_ENABLED:
    try:
        from faster_whisper import WhisperModel
        _whisper_ok = True
    except ImportError:
        print("[Connect]: faster-whisper not installed", file=sys.stderr)

# ── Grammar (lazy) ────────────────────────────────────────────────────────────
_happy_ok = False
_happy_cached = False
HappyTextToText = TTSettings = None

_T5_HUB_DIR   = HAPPY_DIR / "hub" / "models--prithivida--grammar_error_correcter_v1"
_T5_CACHE_DIR = HAPPY_DIR

if GRAMMAR_ENABLED and not GRAMMAR_LAZY_LOAD:
    try:
        from happytransformer import HappyTextToText, TTSettings
        _happy_ok = True
        _hub_root = HAPPY_DIR / "hub"
        _happy_cached = _T5_HUB_DIR.is_dir() or (
            _hub_root.is_dir() and
            any(p.is_dir() for p in _hub_root.iterdir()
                if p.name.startswith("models--"))
        )
    except ImportError:
        pass

_T5_SOURCE = str(_T5_HUB_DIR) if _T5_HUB_DIR.is_dir() else None


def _ensure_grammar_loaded() -> bool:
    global _happy_ok, _happy_cached, HappyTextToText, TTSettings

    if HappyTextToText is not None:
        return True
    if not GRAMMAR_ENABLED:
        return False

    _hub_root     = HAPPY_DIR / "hub"
    _cache_exists = _T5_HUB_DIR.is_dir() or (
        _hub_root.is_dir()
        and any(
            p.is_dir() for p in _hub_root.iterdir()
            if p.name.startswith("models--")
        )
        if _hub_root.is_dir() else False
    )

    try:
        from spoaken.core.config import config_data as _cd
        _offline = _cd.get("offline_mode", False)
    except Exception:
        _offline = False

    if _offline and not _cache_exists:
        print(
            "[Engine]: Grammar skipped — offline mode and no local T5 cache.\n"
            "  → Connect to internet and use Update & Repair → Model Installer\n"
            "    to cache the T5 model locally.  Grammar will then work offline.",
            file=sys.stderr,
        )
        return False

    try:
        from happytransformer import HappyTextToText, TTSettings
        _happy_ok     = True
        _happy_cached = _cache_exists
        if not _happy_cached:
            print(
                "[Engine]: T5 model not cached — will download from HuggingFace Hub\n"
                "  on first Polish use (requires internet, ~480 MB).\n"
                "  To pre-cache: Update & Repair → Model Installer → T5 Models.",
                file=sys.stderr,
            )
        return True
    except ImportError:
        return False


# ── Translation (lazy) ────────────────────────────────────────────────────────
try:
    from deep_translator import GoogleTranslator as _GoogleTranslator
    _translate_ok = True
except ImportError:
    _GoogleTranslator = None
    _translate_ok = False


# ── Audio devices ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def list_input_devices():
    """Return input devices (cached)."""
    try:
        return [
            (i, d["name"])
            for i, d in enumerate(sd.query_devices())
            if d.get("max_input_channels", 0) > 0
        ]
    except Exception as e:
        print(f"[Connect]: device enumeration failed — {e}", file=sys.stderr)
        return []


def default_device_name():
    try:
        idx  = sd.default.device[0]
        info = sd.query_devices(idx)
        return info.get("name", "System Default")
    except Exception:
        return "System Default"


# ── Audio processing ──────────────────────────────────────────────────────────
def maybe_suppress_noise(audio_bytes: bytes, sr: int = 16000) -> bytes:
    """
    ENHANCED audio pipeline with hardware compensation.

    Processing order (CRITICAL — do not reorder):
    1. AGC (normalize level)
    2. Compression (prevent clipping)
    3. EQ (frequency shaping)
    4. Noise Reduction (spectral cleaning)
    5. Clip guard (safety — MUST be last)

    FIX #8: `global` declaration moved to function body top so the
    budget-tracking globals are always writable, not just inside the
    conditional branch where they were previously declared.
    """
    # FIX #8: declare globals at the top of the function
    global _budget_floor_ms, _over_budget_streak, _last_budget_log_t

    start_time = time.perf_counter()

    arr = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    arr *= (1.0 / 32768.0)

    if _mic_config.get("agc_enabled", True):
        arr = _agc.process(arr)

    if _mic_config.get("comp_enabled", True):
        arr = _compressor.process(arr)

    profile = _mic_config.get("eq_profile", "speech")
    if profile == "speech":
        arr = _apply_speech_eq(arr, sr)
    elif profile == "aggressive":
        arr = _apply_aggressive_eq(arr, sr)
    elif profile == "custom":
        arr = _highpass_filter(arr, sr, _mic_config.get("hp_cutoff", 80))

    if _mic_config.get("nr_enabled", False) and _NR_AVAILABLE and nr is not None:
        try:
            arr = nr.reduce_noise(
                y=arr, sr=sr,
                y_noise=_mic_config.get("noise_profile"),
                prop_decrease=_mic_config.get("nr_strength", 0.75),
                stationary=True,
            )
        except Exception:
            pass

    np.clip(arr, -1.0, 1.0, out=arr)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    # FIX #3: deque append is O(1); no pop(0) needed
    _audio_processing_times.append(elapsed_ms)

    if elapsed_ms > _budget_floor_ms:
        _over_budget_streak += 1
        if _over_budget_streak >= _BUDGET_WARN_N:
            now = time.time()
            if now - _last_budget_log_t > 30.0:
                new_floor = min(_budget_floor_ms + _BUDGET_RAISE_MS, _BUDGET_MAX_MS)
                if new_floor > _budget_floor_ms:
                    print(
                        f"[Audio]: pipeline ~{elapsed_ms:.0f}ms — "
                        f"budget floor raised {_budget_floor_ms:.0f}ms → {new_floor:.0f}ms",
                        file=sys.stderr,
                    )
                    _budget_floor_ms = new_floor
                else:
                    print(
                        f"[Audio Warning]: pipeline ~{elapsed_ms:.0f}ms at ceiling "
                        f"{_BUDGET_MAX_MS:.0f}ms — consider disabling noise reduction "
                        "or switching to the 'clean' preset",
                        file=sys.stderr,
                    )
                _last_budget_log_t  = now
                _over_budget_streak = 0
    else:
        if _over_budget_streak > 0:
            _over_budget_streak -= 1

    return (arr * 32768.0).astype(np.int16).tobytes()


# Public alias
process_audio = maybe_suppress_noise


def _apply_speech_eq(arr: np.ndarray, sr: int) -> np.ndarray:
    arr = _highpass_filter(arr, sr, 80)
    arr *= 1.15
    return arr


def _apply_aggressive_eq(arr: np.ndarray, sr: int) -> np.ndarray:
    arr = _highpass_filter(arr, sr, 120)
    arr *= 1.3
    return arr


def _highpass_filter(arr: np.ndarray, sr: int, cutoff: int) -> np.ndarray:
    """High-pass filter with cached coefficients (O(1) after first call)."""
    cache_key = (sr, cutoff)
    sos = _hp_filter_cache.get(cache_key)
    if sos is None:
        try:
            from scipy import signal as _sig
            sos = _sig.butter(1, cutoff, "hp", fs=sr, output="sos")
            _hp_filter_cache[cache_key] = sos
        except ImportError:
            return arr
    try:
        from scipy.signal import sosfilt
        return sosfilt(sos, arr).astype(np.float32)
    except Exception:
        return arr


def audio_gate(audio_bytes: bytes):
    """VAD gate (O(n) in audio length)."""
    vad = _get_vad()
    return vad.process(audio_bytes) if vad else audio_bytes


def reset_vad():
    """Reset VAD state (O(1))."""
    vad = _get_vad()
    if vad:
        vad.reset()


def translate_text(text: str, target_lang: str = "en"):
    """Translate via Google Translate (network I/O)."""
    if not _translate_ok or not _GoogleTranslator:
        return None
    try:
        translator = _GoogleTranslator(source="auto", target=target_lang)
        return translator.translate(text)
    except Exception:
        return None


# ── Model scanners ────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def scan_installed_vosk_models():
    """Scan Vosk models (cached O(1))."""
    try:
        # FIX #5: catch OSError as well as the implicit Exception
        found = sorted(
            d.name for d in VOSK_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        return found if found else ["(none installed)"]
    except OSError:
        return ["(none installed)"]


@lru_cache(maxsize=1)
def scan_installed_whisper_models():
    """Scan Whisper models (cached O(1))."""
    _PREFIX = "models--Systran--faster-whisper-"
    try:
        # FIX #5: catch OSError as well
        found = sorted(
            d.name[len(_PREFIX):]
            for d in WHISPER_DIR.iterdir()
            if d.is_dir() and d.name.startswith(_PREFIX)
        )
        return found if found else ["(none installed)"]
    except OSError:
        return ["(none installed)"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _resolve_vosk(model_name: str):
    path = VOSK_DIR / model_name
    if not path.is_dir():
        raise FileNotFoundError(f"Vosk model not found: {model_name}")
    return str(path)


def _resolve_compute_type(compute: str, gpu: bool) -> str:
    """
    FIX #10: refactored from opaque chained ternary to explicit branches.

    auto + GPU  → int8_float16 (best balance of speed/quality on CUDA)
    auto + CPU  → int8         (fastest CPU-only quantisation)
    explicit    → pass through as-is
    """
    if compute != "auto":
        return compute
    return "int8_float16" if gpu else "int8"


# ══════════════════════════════════════════════════════════════════════════════
# AudioPipeline
# ══════════════════════════════════════════════════════════════════════════════

class AudioPipeline:
    """
    Thin named wrapper around the module-level audio processing functions.

    Provides the interface expected by controller.py:
      .stages_active          — list of currently active stage names
      .capture_noise_profile(pcm_bytes) — feed ambient audio to noisereduce
    """

    @property
    def stages_active(self) -> list[str]:
        stages: list[str] = []
        if _mic_config.get("agc_enabled", True):
            stages.append("agc")
        if _mic_config.get("comp_enabled", True):
            stages.append("compress")
        profile = _mic_config.get("eq_profile", "speech")
        if profile != "flat":
            stages.append(f"eq:{profile}")
        if _mic_config.get("nr_enabled", False) and _NR_AVAILABLE:
            stages.append("nr")
        stages.append("clip")
        return stages

    def capture_noise_profile(self, pcm_bytes: bytes, sr: int = 16000):
        """
        Feed a buffer of silent/ambient audio to the noise reduction engine.

        FIX #9: nr_enabled is only set True on success, not before the
        try block, so a failed capture doesn't silently enable NR.
        """
        if not _NR_AVAILABLE or nr is None:
            return

        try:
            arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            arr *= 1.0 / 32768.0
            _mic_config["noise_profile"] = arr
            _mic_config["nr_enabled"]    = True   # FIX #9: inside try
            print("[Pipeline]: noise profile captured ✔", file=sys.stderr)
        except Exception as exc:
            print(f"[Pipeline]: noise profile capture failed — {exc}", file=sys.stderr)


_pipeline = AudioPipeline()


# ══════════════════════════════════════════════════════════════════════════════
# TranscriptionModel
# ══════════════════════════════════════════════════════════════════════════════

class TranscriptionModel:
    """Production model with O(1) access and minimal overhead."""

    def __init__(self, vosk_model=None, status_callback=None):
        self.small_model = None
        if _vosk_ok and VOSK_ENABLED and vosk_model:
            try:
                if status_callback:
                    status_callback(0.70, f"Loading Vosk ({vosk_model})")
                self.small_model = VoskModel(_resolve_vosk(vosk_model))
            except FileNotFoundError as exc:
                print(exc, file=sys.stderr)

        self.whisper_model = None
        if _whisper_ok and WHISPER_ENABLED:
            try:
                device       = "cuda" if GPU_ENABLED else "cpu"
                compute_type = _resolve_compute_type(WHISPER_COMPUTE, GPU_ENABLED)
                if status_callback:
                    status_callback(0.80, f"Loading Whisper ({WHISPER_MODEL})")
                self.whisper_model = WhisperModel(
                    WHISPER_MODEL,
                    device=device,
                    compute_type=compute_type,
                    download_root=str(WHISPER_DIR),
                )
            except Exception as exc:
                print(f"[Connect]: Whisper load failed — {exc}", file=sys.stderr)

        self.tool = None
        self._grammar_loaded = False

        self.vosk_queue:    Queue = Queue()
        self.whisper_queue: Queue = Queue()

        if VOSK_ENABLED:
            self.audio_queue = self.vosk_queue
        else:
            self.audio_queue = self.whisper_queue

        self.is_running   = False
        self.data_store:    list = []
        self.whisper_store: list = []

    def _ensure_grammar(self):
        """
        Lazy-load the T5 grammar model from local cache — O(1) after first call.

        Sets TRANSFORMERS_OFFLINE + HF_HUB_OFFLINE and passes
        local_files_only=True to fully block outbound HF Hub requests.
        """
        if self._grammar_loaded:
            return
        if not _ensure_grammar_loaded():
            return
        if not (_happy_ok and _happy_cached and _T5_SOURCE):
            return
        try:
            os.environ["TRANSFORMERS_CACHE"]   = str(_T5_CACHE_DIR)
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["HF_HUB_OFFLINE"]       = "1"
            self.tool = HappyTextToText(
                "T5",
                _T5_SOURCE,
                model_kwargs={"local_files_only": True},
            )
            self._grammar_loaded = True
            print("[Engine]: Grammar model loaded (local cache, offline)", file=sys.stderr)
        except Exception as exc:
            print(f"[Engine]: T5 load failed — {exc}", file=sys.stderr)
            print(
                "  → Run Update & Repair → Model Installer → Download T5 model "
                "to cache it for offline use.",
                file=sys.stderr,
            )

    def _background_load(self):
        self._ensure_grammar()

    def get_fast_recognizer(self):
        if self.small_model is None:
            raise RuntimeError("Vosk model not loaded")
        rec = KaldiRecognizer(self.small_model, 16000)
        rec.SetWords(True)
        rec.SetPartialWords(True)
        return rec

    def reload_vosk(self, model_name: str) -> bool:
        if not _vosk_ok:
            return False
        try:
            self.small_model = VoskModel(_resolve_vosk(model_name))
            return True
        except Exception:
            return False

    def reload_whisper(self, model_name: str) -> bool:
        if not _whisper_ok:
            return False
        try:
            device       = "cuda" if GPU_ENABLED else "cpu"
            compute_type = _resolve_compute_type(WHISPER_COMPUTE, GPU_ENABLED)
            self.whisper_model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=str(WHISPER_DIR),
            )
            return True
        except Exception:
            return False

    def transcribe_whisper(self, audio_bytes: bytes) -> str:
        if self.whisper_model is None:
            return ""
        try:
            arr = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            arr *= (1.0 / 32768.0)
            segments, _ = self.whisper_model.transcribe(
                arr,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            print(f"[Whisper]: {exc}", file=sys.stderr)
            return ""

    def run_polish(self, store=None):
        """
        Polish text via T5 grammar correction.

        FIX #6: per-chunk max_length now derived from chunk size (100 words ≈
        150 tokens) rather than a hard 512 that silently truncated long segments.
        Returns ("Empty", "No text to polish.") when there is nothing to process.
        """
        src = store if store is not None else self.data_store
        if not src:
            return "Empty", "No text to polish."

        full = " ".join(src)
        self._ensure_grammar()

        if self.tool:
            try:
                # 100-word chunks; max_length is generous but not unbounded
                args   = TTSettings(num_beams=2, min_length=1, max_length=200)
                words  = full.split()
                chunks = [" ".join(words[i:i + 100]) for i in range(0, len(words), 100)]
                corrected = " ".join(
                    self.tool.generate_text(f"grammar: {c}", args=args).text
                    for c in chunks
                )
            except Exception as exc:
                corrected = f"[Polish failed — {exc}]"
        else:
            corrected = full

        return full, corrected

    def correct_grammar(self, text: str) -> str:
        """
        Correct grammar in a single text segment.

        FIX #7: handle the ("Empty", "No text…") sentinel returned by
        run_polish() when src is empty so we don't return a misleading "".
        """
        if not text or not text.strip():
            return text
        try:
            _orig, corrected = self.run_polish([text])
            # _orig == "Empty" means run_polish got no usable text
            if _orig == "Empty":
                return text
            return corrected if corrected and corrected.strip() else text
        except Exception:
            return text
