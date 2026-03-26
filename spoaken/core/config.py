"""
core/config.py
──────────────
Central runtime configuration for Spoaken.

Reads spoaken_config.json (written by the installer) and exposes every
setting as a typed module-level constant.  All other modules import from
here rather than reading JSON directly.

Fallback defaults match a fresh Whisper-only install with minimal optional
features enabled, so the app starts safely even without a config file.

Install path:  <install_dir>/spoaken/core/config.py
Config path:   <install_dir>/spoaken_config.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Locate install root ───────────────────────────────────────────────────────
# spoaken/core/config.py  →  parent = spoaken/core/  →  parent = spoaken/
#   →  parent = <install_dir>/
_HERE        = Path(__file__).resolve().parent   # spoaken/core/
_SPOAKEN_DIR = _HERE.parent                       # spoaken/
_ROOT        = _SPOAKEN_DIR.parent                # <install_dir>/

_CONFIG_CANDIDATES: list[Path] = [
    _ROOT        / "spoaken_config.json",   # standard install location
    _SPOAKEN_DIR / "spoaken_config.json",   # legacy / dev layout
    Path.home()  / ".spoaken" / "config.json",  # user-home fallback
]

config_data: dict = {}
_loaded_from: Path | None = None

for _candidate in _CONFIG_CANDIDATES:
    if _candidate.exists():
        try:
            with open(_candidate, encoding="utf-8") as _fh:
                config_data = json.load(_fh)
            _loaded_from = _candidate
            break
        except Exception as _parse_err:
            print(
                f"[Config]: could not parse {_candidate}: {_parse_err}",
                file=sys.stderr,
            )

if not config_data:
    print(
        "[Config]: spoaken_config.json not found — using built-in defaults.\n"
        "  Run the installer to generate a config file:\n"
        "    ./install.sh",
        file=sys.stderr,
    )


# ── Type-safe getter ──────────────────────────────────────────────────────────

def _get(key: str, default):
    """
    Return config_data[key] cast to the same type as *default*, or *default*
    if the key is absent or the value is None.

    Using the type of the default avoids silent bool/int/str mismatches that
    can arise when the JSON was hand-edited.
    """
    val = config_data.get(key)
    if val is None:
        return default
    try:
        return type(default)(val)
    except (TypeError, ValueError):
        return default


# ── Transcription engines ─────────────────────────────────────────────────────

VOSK_ENABLED    : bool = bool(_get("vosk_enabled",    False))
WHISPER_ENABLED : bool = bool(_get("whisper_enabled", True))
WHISPER_MODEL   : str  = str(_get("whisper_model",    "base.en"))
WHISPER_COMPUTE : str  = str(_get("whisper_compute",  "auto"))
GPU_ENABLED     : bool = bool(_get("gpu",             False))
ENGINE_MODE     : str  = str(_get("engine_mode",      "auto"))

# Small/fast Vosk model used for real-time partial transcription.
# Falls back to the most common small English model when unset in config.
QUICK_VOSK_MODEL: str = str(
    config_data.get("vosk_model") or "vosk-model-small-en-us-0.15"
)

# ── Grammar / T5 ──────────────────────────────────────────────────────────────

GRAMMAR_ENABLED   : bool = bool(_get("grammar",           True))
GRAMMAR_LAZY_LOAD : bool = bool(_get("grammar_lazy_load", True))
T5_MODEL          : str  = str(_get("t5_model",           "vennify/t5-base-grammar-correction"))

# ── Audio pipeline ────────────────────────────────────────────────────────────

NOISE_SUPPRESSION : bool = bool(_get("noise_suppression", False))

# mic_device: None / -1 both mean "system default"; store as None internally.
_raw_mic = config_data.get("mic_device")
MIC_DEVICE: int | None = (
    int(_raw_mic)
    if _raw_mic not in (None, -1, "", "null")
    else None
)

# ── Transcript memory ─────────────────────────────────────────────────────────

MEMORY_CAP_WORDS   : int  = int(_get("memory_cap_words",   2000))
MEMORY_CAP_MINUTES : int  = int(_get("memory_cap_minutes", 60))
DUPLICATE_FILTER   : bool = bool(_get("duplicate_filter",  True))
ENABLE_PARTIALS    : bool = bool(_get("enable_partials",   False))

# ── LAN / networking ──────────────────────────────────────────────────────────

CHAT_SERVER_ENABLED   : bool = bool(_get("chat_server_enabled",    False))
CHAT_SERVER_PORT      : int  = int(_get("chat_server_port",         55300))
CHAT_SERVER_TOKEN     : str  = str(_get("chat_server_token",        "spoaken"))
ANDROID_STREAM_ENABLED: bool = bool(_get("android_stream_enabled", False))
ANDROID_STREAM_PORT   : int  = int(_get("android_stream_port",      55301))

# ── Performance ───────────────────────────────────────────────────────────────

BACKGROUND_MODE        : bool = bool(_get("background_mode",         False))
AUDIO_LOOKAHEAD_BUFFER : int  = int(_get("audio_lookahead_buffer",    4))

# ── Miscellaneous ─────────────────────────────────────────────────────────────

FIRST_RUN_SHOWN : bool = bool(_get("first_run_shown", False))
OFFLINE_MODE    : bool = bool(_get("offline_mode",    False))
LOG_UNLIMITED   : bool = bool(_get("log_unlimited",   True))

# ── Sanity guard ──────────────────────────────────────────────────────────────
# If both engines are disabled (can only happen via hand-edited config), enable
# Whisper so the app still starts rather than hanging at the recording stage.

if not VOSK_ENABLED and not WHISPER_ENABLED:
    print(
        "[Config]: WARNING — both vosk_enabled and whisper_enabled are False.\n"
        "  Enabling Whisper as fallback.  Edit spoaken_config.json to fix this.",
        file=sys.stderr,
    )
    WHISPER_ENABLED = True
