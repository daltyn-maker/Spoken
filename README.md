# Spoaken — Complete Documentation

> Real-time voice-to-text with Whisper + Vosk · LAN Chat · Grammar Correction · LLM summarization

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Launching Spoaken](#launching-spoaken)
5. [Directory Layout](#directory-layout)
6. [Configuration Reference](#configuration-reference)
7. [Audio Pipeline](#audio-pipeline)
8. [Voice Activity Detection (VAD)](#voice-activity-detection-vad)
9. [Transcription Engines](#transcription-engines)
10. [Grammar Correction (T5)](#grammar-correction-t5)
11. [LLM Integration (Ollama)](#llm-integration-ollama)
12. [Summarization](#summarization)
13. [Noise Reduction](#noise-reduction)
14. [LAN Chat](#lan-chat)
15. [Online Relay (Tor)](#online-relay-tor)
16. [Android / Browser Live Stream](#android--browser-live-stream)
17. [Window Writer](#window-writer)
18. [Session Recovery](#session-recovery)
19. [Crash Logging](#crash-logging)
20. [Voice Commands](#voice-commands)
21. [Update and Repair Window](#update-and-repair-window)
22. [Module Reference](#module-reference)
23. [Platform Notes](#platform-notes)
24. [Troubleshooting](#troubleshooting)
25. [CLI Reference](#cli-reference)

---

## Overview

Spoaken is a desktop voice-to-text application that runs entirely on your local machine. No cloud speech API is required — all transcription, grammar correction, and summarization happens on-device. Optional online features (Tor P2P chat, cloud translation) can be added or removed at any time.

**Core features:**

- Dual-engine ASR: Whisper (accuracy) and Vosk (speed/low-RAM)
- Auto engine selection based on available RAM
- Full audio pipeline: AGC → compressor → EQ → noise reduction → clip guard
- Grammar correction via local T5 model (HappyTransformer)
- LLM summarization and translation via Ollama
- LAN WebSocket chat between Spoaken instances
- Live transcript stream to Android or browsers (SSE)
- Window Writer — types transcribed text directly into any application window
- Session auto-save with crash recovery
- Voice commands parsed from the live transcription stream
- Multi-platform: Windows 10/11, macOS 12+, Ubuntu/Debian, Fedora/RHEL, Arch Linux

---

## Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.9 | 3.11+ |
| RAM | 2 GB | 8 GB |
| Disk | 3 GB | 8 GB (with large models) |
| Microphone | Any | USB or XLR interface |
| GPU | Not required | NVIDIA CUDA (optional) |

**System packages installed automatically:**

| Platform | Packages |
|----------|----------|
| Ubuntu/Debian | ffmpeg portaudio19-dev python3-dev python3-pip python3.X-venv python3-tk wmctrl xdotool tor build-essential |
| Fedora/RHEL | ffmpeg portaudio-devel python3-devel python3-pip python3-tkinter wmctrl xdotool tor gcc |
| Arch Linux | ffmpeg portaudio python python-pip tk wmctrl xdotool tor base-devel |
| macOS | ffmpeg portaudio (via Homebrew) |
| Windows | FFmpeg (via winget) |

---

## Installation

### Linux and macOS

```bash
git clone https://github.com/daltyn-maker/Spoaken.git
cd Spoaken
chmod +x install.sh
./install.sh
```

The shell script provides a full Linux-style installer experience:
- Phase tracking [1/3], [2/3], [3/3] with section dividers
- Animated spinner for blocking operations
- ASCII progress bars for install steps
- Disk-space and connectivity pre-checks
- macOS Accessibility permission reminder before anything installs

### Windows

```powershell
git clone https://github.com/daltyn-maker/Spoaken.git
cd Spoaken
python install.py --interactive
```

### What the installer does

1. Creates a Python virtual environment at `<install_dir>/venv/`
2. Installs system packages (ffmpeg, portaudio, etc.)
3. Upgrades pip, setuptools, and wheel inside the venv
4. Installs all Python packages into the venv
5. Copies the `spoaken/` source tree to `<install_dir>/spoaken/`
6. Pre-downloads the Whisper model (~145 MB for base.en)
7. Optionally downloads a Vosk model
8. Writes `<install_dir>/spoaken_config.json` — created once, user edits are preserved on re-installs
9. Creates a desktop shortcut and application menu entry
10. Removes the install-time download cache from `<install_dir>/cache/`

Default install locations:

| Platform | Default |
|----------|---------|
| Linux | `~/Spoaken` |
| macOS | `/Applications/Spoaken` |
| Windows | `C:\Program Files\Spoaken` |

### Offline installation

If no internet is available the installer runs in offline mode automatically. Tor P2P and cloud translation are skipped. To add them later:

```bash
python install.py --online-only
```

---

## Launching Spoaken

### Preferred: run.sh (Linux and macOS)

```bash
~/Spoaken/run.sh
```

`run.sh` activates the venv and starts the app. It always works regardless of which Python is active in your shell.

The terminal you launch from will always print:

```
[Spoaken]: ─────────────────────────────────────────────
[Spoaken]: Installed at:  /home/user/Spoaken
[Spoaken]: Run anytime :  /home/user/Spoaken/run.sh
[Spoaken]: ─────────────────────────────────────────────
```

This appears before the GUI opens so you always know the install location.

### Manual (venv activated)

```bash
source ~/Spoaken/venv/bin/activate
python -m spoaken
```

### Windows

```powershell
~\Spoaken\venv\Scripts\python.exe -m spoaken
# or double-click the Desktop shortcut
```

### Desktop shortcut

The installer creates platform-appropriate shortcuts:
- **Linux**: `~/.local/share/applications/spoaken.desktop` and `~/Desktop/Spoaken.desktop`
- **macOS**: `/Applications/Spoaken.command`
- **Windows**: `~/Desktop/Spoaken.lnk`

---

## Directory Layout

```
<install_dir>/                      user-chosen directory (default ~/Spoaken)
|
|-- spoaken_config.json             single runtime config (created once by installer)
|-- run.sh                          launcher (activates venv and starts app)
|
|-- venv/                           Python virtual environment
|   |-- bin/python                  Unix venv Python
|   `-- Scripts/python.exe          Windows venv Python
|
|-- models/
|   |-- whisper/                    faster-whisper model cache
|   `-- vosk/                       Vosk model folders
|
|-- logs/
|   |-- log.txt                     unified session log (all ASR output)
|   |-- llm_summary.txt             LLM summaries (when enabled)
|   |-- llm_translation.txt         LLM translations (when enabled)
|   `-- crashes/                    crash reports (auto-generated)
|
`-- spoaken/                        application source package
    |-- __init__.py                 package root (v2.1.1)
    |-- __main__.py                 entry point: python -m spoaken
    |
    |-- core/
    |   |-- config.py               configuration loader and constants
    |   |-- engine.py               TranscriptionModel and AudioPipeline
    |   `-- vad.py                  Voice Activity Detection
    |
    |-- ui/
    |   |-- gui.py                  main window (customtkinter)
    |   `-- splash.py               startup splash screen
    |
    |-- network/
    |   |-- chat.py                 re-export compatibility layer
    |   |-- lan.py                  LAN WebSocket server and client
    |   `-- online.py               Tor relay server and client
    |
    |-- processing/
    |   |-- llm.py                  LLM, grammar, translation
    |   |-- summarize.py            TF-IDF extractive summarization
    |   |-- summarize_router.py     unified summarize() with fallback chain
    |   `-- writer.py               DirectWindowWriter
    |
    |-- system/
    |   |-- crashlog.py             crash reporting and global handler
    |   |-- environ.py              CPU and RAM monitoring
    |   |-- mic_config.py           audio device configuration UI
    |   |-- paths.py                path resolver (models, logs, assets)
    |   `-- session_recovery.py     auto-save and crash recovery
    |
    `-- control/
        |-- commands.py             voice command parser
        |-- controller.py           TranscriptionController (main logic)
        `-- update.py               Update and Repair window
```

---

## Configuration Reference

Spoaken reads `<install_dir>/spoaken_config.json` at startup.

The config is **created once** by the installer. Re-installing or running repair merges new keys in without overwriting values you have already changed. Paths and venv location are always updated on re-install.

All values can be changed via **Update, Install and Repair** without editing the file manually.

### Engine

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `engine_mode` | string | `"auto"` | `"auto"` selects Vosk below 4 GB RAM, Whisper otherwise. Also accepts `"vosk_only"` `"whisper_only"` `"both"`. |
| `vosk_enabled` | bool | `true` | Enable Vosk engine. |
| `vosk_model` | string | `"vosk-model-small-en-us-0.15"` | Active Vosk model name (folder in models/vosk/). |
| `vosk_model_accurate` | string | `"vosk-model-en-us-0.42-gigaspeech"` | High-accuracy model used when `enable_giga_model` is true. |
| `enable_giga_model` | bool | `false` | Use the gigaspeech model automatically when RAM allows. |
| `whisper_enabled` | bool | `true` | Enable Whisper engine. |
| `whisper_model` | string | `"base.en"` | Model name. Options: `tiny.en` `base.en` `small.en` `medium.en` `large-v3`. |
| `whisper_compute` | string | `"auto"` | Compute type: `"auto"` `"int8"` `"float16"` `"float32"`. |

### Hardware

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `gpu` | bool | `false` | Enable GPU/CUDA for Whisper and T5 inference. |
| `mic_device` | int or null | `null` | sounddevice device index. null uses the system default. |
| `noise_suppression` | bool | `false` | Enable noisereduce spectral gating. |

### Audio Pipeline

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `audio_preset` | string | `"budget"` | Hardware preset: `"studio"` `"headset"` `"budget"` `"laptop"` `"phone"`. |
| `eq_profile` | string | `"speech"` | EQ preset: `"speech"` `"flat"` `"presence"` `"warmth"`. |
| `hp_cutoff` | int | `80` | High-pass filter cutoff in Hz. Removes low-frequency rumble. |
| `nr_strength` | float | `0.75` | Noise reduction strength 0.0 to 1.0. |
| `comp_threshold_db` | float | `-18.0` | Compressor threshold in dBFS. |
| `comp_ratio` | float | `4.0` | Compressor ratio. 4.0 means 4:1. |
| `agc_target_rms` | float | `0.15` | AGC target RMS level 0.0 to 1.0. |
| `agc_max_gain_db` | float | `12.0` | Maximum AGC gain in dB to prevent noise amplification. |

### VAD

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `vad_aggressiveness` | int | `2` | WebRTC VAD aggressiveness 0 to 3. 0 least aggressive, 3 most. |
| `vad_min_speech_ms` | int | `200` | Minimum speech duration to emit a segment (ms). |
| `vad_silence_gap_ms` | int | `500` | Silence gap before finalizing a segment (ms). |
| `vad_energy_threshold` | float | `0.015` | Energy-gate threshold used when webrtcvad is unavailable. |
| `vad_config_persist` | bool | `true` | Save VAD changes back to config when adjusted via the UI. |

### Grammar

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `grammar` | bool | `true` | Enable T5 grammar correction packages. |
| `grammar_lazy_load` | bool | `true` | Load T5 model on first use instead of at startup. |
| `t5_model` | string | `"vennify/t5-base-grammar-correction"` | HuggingFace model ID. |
| `offline_mode` | bool | `false` | When true, T5 only loads from local cache. No HuggingFace download. |

### Memory and Text Quality

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `memory_cap_words` | int | `2000` | Auto-polish and clear transcript after this many words. |
| `memory_cap_minutes` | int | `60` | Auto-polish after this many minutes of active recording. |
| `duplicate_filter` | bool | `true` | Silently discard repeated segments from ASR. |
| `enable_partials` | bool | `false` | Show Vosk partial results in real time while speaking. |
| `log_unlimited` | bool | `true` | Single unlimited log file with no rotation or size cap. |

### Network

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `chat_server_enabled` | bool | `false` | Start LAN chat server at launch. |
| `chat_server_port` | int | `55300` | LAN chat WebSocket port. |
| `chat_server_token` | string | `"spoaken"` | Auth token for LAN chat. Change before enabling. |
| `android_stream_enabled` | bool | `false` | Start SSE live-transcript stream at launch. |
| `android_stream_port` | int | `55301` | SSE stream HTTP port. |

### Performance

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `llm_lazy_load` | bool | `true` | Load Ollama client on first use. |
| `background_mode` | bool | `false` | Headless mode — no GUI, console-only output. |
| `audio_lookahead_buffer` | int | `4` | Audio lookahead buffer depth in blocks. Higher = smoother VAD. |

### Paths (auto-managed by installer)

| Key | Description |
|-----|-------------|
| `install_dir` | Root of the installed application. |
| `venv_dir` | Path to the virtual environment. Always `<install_dir>/venv`. |
| `whisper_dir` | Whisper model cache directory. |
| `vosk_dir` | Vosk model root directory. |
| `platform` | `"Windows"` `"Darwin"` or `"Linux"` — set at install time. |

---

## Audio Pipeline

Every audio block passes through this chain before being sent to ASR:

```
Microphone  (16 kHz, int16, mono)
       |
       v
  1. SimpleAGC           Automatic Gain Control
                         Normalises quiet speakers without amplifying noise.
                         target_rms  =  agc_target_rms  (default 0.15)
                         max_gain    =  agc_max_gain_db  (default 12 dB)
       |
       v
  2. DynamicCompressor   Prevents plosive clipping and tames signal peaks.
                         threshold  =  comp_threshold_db  (default -18 dBFS)
                         ratio      =  comp_ratio          (default 4:1)
       |
       v
  3. ParametricEQ        Frequency shaping for speech clarity.
                         high-pass  =  hp_cutoff   (default 80 Hz)
                         profile    =  eq_profile  (default "speech")
       |
       v
  4. NoiseReducer        Spectral gating via noisereduce  (optional).
                         strength   =  nr_strength  (default 0.75)
                         Only active when noise_suppression = true.
       |
       v
  5. ClipGuard           Hard limiter — always last.
                         Prevents digital clipping before the ASR engine sees audio.
       |
       v
  ASR Engine  (Vosk or Whisper)
```

### Hardware Presets

Presets tune the entire pipeline for common microphone types:

| Preset | Intended hardware |
|--------|------------------|
| `studio` | Condenser mic in a quiet room |
| `headset` | Gaming or communications headset |
| `budget` | Cheap USB microphone (installer default) |
| `laptop` | Built-in laptop microphone |
| `phone` | Phone audio or speakerphone input |

Apply via GUI: **Mic Setup > Hardware Preset** or set `audio_preset` in config.

### Noise Profile Auto-Capture

When recording starts, Spoaken captures approximately one second of ambient audio before the main stream opens. This is used as the stationary noise reference for noisereduce. The capture runs in a background thread so startup is not delayed. If it fails (exclusive-mode device, WASAPI restriction, etc.) the error is logged and recording continues without a noise profile.

---

## Voice Activity Detection (VAD)

Two VAD implementations are supported. The best available is selected automatically.

**WebRTC VAD** (preferred) uses Google's `webrtcvad` library. Requires a C compiler to install. Provides reliable frame-level speech and silence detection.

**Energy-gate fallback** is pure Python. Used when `webrtcvad` is not installed or when `--no-vad` was passed to the installer. Less accurate on noisy inputs but always available without compilation.

All VAD settings live in the main `spoaken_config.json`. The separate `vad_config.json` file from earlier versions is no longer used and can be deleted.

Changes made in **Mic Setup** are saved back to config automatically when `vad_config_persist` is true.

---

## Transcription Engines

### Vosk

Best for low-RAM machines (under 4 GB), low-latency requirements, or when offline is a strict requirement.

Model directory: `<install_dir>/models/vosk/`

Available models (install via Update and Repair > Model Installer):

| Model | Size | Accuracy |
|-------|------|----------|
| `vosk-model-small-en-us-0.15` | 40 MB | Good |
| `vosk-model-en-us-0.22` | 1.8 GB | Better |
| `vosk-model-en-us-0.42-gigaspeech` | 2.3 GB | Best |

### Whisper (faster-whisper)

Best for high accuracy on machines with 6 GB or more of available RAM.

Model directory: `<install_dir>/models/whisper/`

| Model | Size | Notes |
|-------|------|-------|
| `tiny.en` | 75 MB | Fastest, lower accuracy |
| `base.en` | 145 MB | Default — good balance |
| `small.en` | 466 MB | Better accuracy |
| `medium.en` | 1.5 GB | High accuracy |
| `large-v3` | 3.1 GB | Best accuracy, needs 8 GB+ RAM |

### Switching Engines

Via GUI: toggle button in the main window.  
Via voice: `spoaken.engine(vosk)` or `spoaken.engine(whisper)`.  
Via config: set `engine_mode` to `"vosk_only"` or `"whisper_only"` and relaunch.

Switching unloads the inactive model from RAM immediately and forces a garbage collection pass.

---

## Grammar Correction (T5)

Grammar correction uses a local T5 transformer — no Google API or cloud service.

- **Model**: `vennify/t5-base-grammar-correction` (~480 MB)
- **Downloaded from**: HuggingFace Hub on first use (not at install time)
- **Offline after**: once the model is cached, it works with no internet connection

**Lazy loading**: The model is not loaded at startup. It loads the first time you press Polish or enable live grammar. After loading it stays in RAM.

**Live grammar**: Enable in the GUI to automatically correct each transcribed segment. The original text is replaced with the corrected version in the transcript.

**Polish**: Applies grammar correction to the full current transcript in one batch.

To preload the model during install for completely offline use afterward, trigger a Polish immediately after the first launch while internet is available. The cache at `~/.cache/huggingface/hub/` persists across launches.

---

## LLM Integration (Ollama)

Spoaken connects to [Ollama](https://ollama.com) for local LLM summarization and translation. Ollama must be installed and running separately.

```bash
# Install Ollama from https://ollama.com/download
# Then pull a model:
ollama pull llama3.2
```

### Modes

| Mode | What it does |
|------|-------------|
| `summarize` | Summarizes each growing chunk of transcript in the background |
| `translate` | Translates transcript output to the selected target language |

### Background chunk processing

As you speak, Spoaken accumulates words and fires a background thread when the new-word count exceeds the `llm_chunk_budget`. The budget is auto-adjusted by `SysEnviron` based on available RAM (40 words below 4 GB, 80 words up to 8 GB, 150 words above 8 GB). LLM processing is skipped entirely when CPU load exceeds 50%.

---

## Summarization

`summarize_router.py` provides a single `summarize(text)` function with a three-stage fallback chain:

1. **Ollama LLM** — if running and the llm module is available
2. **Extractive TF-IDF** via `sumy` and `scikit-learn` — always available once installed
3. **Hard truncation** — last resort, never raises, never fails

Summarization works at every install level including a minimal install with no optional packages.

```python
from spoaken.processing.summarize_router import summarize, is_llm_available
result = summarize("long transcript text")
```

---

## Noise Reduction

Uses **noisereduce** (spectral gating). Runs fully locally — no API calls, no usage limits, no added network latency. `scipy` is its only non-trivial dependency. Both are installed by default.

Enable or disable via the GUI noise toggle or `noise_suppression` in config.  
Adjust strength via `nr_strength` (0.0 to 1.0).

A noise profile captured at session start improves accuracy significantly. See [Audio Pipeline](#audio-pipeline) above.

---

## LAN Chat

Spoaken instances on the same local network can connect over WebSockets.

**Architecture**: One instance runs as a server (`SpoakenLANServer`). Others connect as clients (`SpoakenLANClient`). A UDP beacon lets clients discover the server automatically without manual IP entry.

**Features**:
- Text messaging between instances
- Live transcript broadcast to connected clients
- File transfer between instances
- Room and user management
- Auth token validation per connection

**Enable**: Set `chat_server_enabled = true` and set a port and token.

**Security note**: Change `chat_server_token` from the default `"spoaken"` before enabling. The default is intentionally flagged with a warning on startup.

---

## Online Relay (Tor)

Available only with online-mode installs. Spoaken can relay transcripts and chat between instances over the internet using a Tor hidden service.

Required packages (installed via `--online` or `--online-only`):
- `stem` — Tor control library
- `PySocks` — SOCKS5 proxy support
- `aiohttp` and `aiofiles` — async HTTP relay

Also requires the Tor daemon running on the system (installed automatically on Linux).

Enable via **Update, Install and Repair > Online Packages**.

---

## Android and Browser Live Stream

Spoaken can stream the live transcript to any browser or Android device on the same network using HTTP Server-Sent Events.

Enable: set `android_stream_enabled = true` and configure `android_stream_port` (default 55301).  
View: open `http://<machine-ip>:55301/` in any browser.

No app install required on the receiving device. The page auto-updates as new transcript segments arrive.

---

## Window Writer

The Window Writer types transcribed text directly into any application window as if it were keyboard input.

**Usage**:
1. Enter the target window title in the Target field
2. Click Lock to attach to that window
3. Enable Write — every finalized transcript segment is typed into the target

**Platform implementations**:

| Platform | Method |
|----------|--------|
| Windows | pywinauto + pywin32 |
| macOS | pyautogui |
| Linux X11 | xdotool |
| Linux Wayland | pyautogui fallback (no title targeting) |

For Wayland users who need title targeting, log out and choose the Xorg session at the login screen.

---

## Session Recovery

Spoaken saves the current transcript to a JSON file every 60 seconds while recording is active. If the process is killed unexpectedly, the next launch detects the saved session.

**Storage location**: `~/.spoaken/session_recovery.json`  
**Format**: JSON (not pickle — safe, human-readable, survives Python version changes)  
**Maximum age**: Sessions older than 24 hours are automatically discarded  
**Clean exit**: The recovery file is deleted on a normal stop or close

On the next launch after a crash, a Restore / Discard prompt appears in the transcript area. Restored segments are reinserted into the transcript with `[Restored]` labels.

Migration from legacy pickle format is handled automatically on first run — the old `.pkl` file is converted and deleted.

---

## Crash Logging

A global exception handler catches all unhandled exceptions and writes a detailed report to `<install_dir>/logs/crashes/`. Each report includes:

- Exception type, message, and full traceback
- Python version and platform information
- Timestamp and context label identifying which subsystem crashed

The handler is installed before any other import in `__main__.py`, so even import-time failures are captured.

Background threads that encounter exceptions log via `_crashlog(context, exc)` in the controller rather than letting exceptions silently vanish.

---

## Voice Commands

Spoaken parses voice commands from the transcription stream. Commands are only evaluated for short segments (15 words or fewer) to prevent false triggers on normal speech.

### Command syntax

```
spoaken.command(argument)     function call style
spoaken command argument      natural speech style
```

### Built-in commands

| Command | Aliases | Description |
|---------|---------|-------------|
| `spoaken.start()` | `start recording` | Start recording |
| `spoaken.stop()` | `stop recording` | Stop recording |
| `spoaken.polish()` | `fix that`, `correct that` | Run grammar correction on full transcript |
| `spoaken.clear()` | `clear screen`, `wipe it` | Clear transcript and logs |
| `spoaken.copy()` | `copy that` | Copy transcript to clipboard |
| `spoaken.write()` | `start typing` | Enable window writer |
| `spoaken.nowrite()` | `stop typing` | Disable window writer |
| `spoaken.engine(vosk)` | `use vosk` | Switch to Vosk engine |
| `spoaken.engine(whisper)` | `use whisper` | Switch to Whisper engine |
| `spoaken.summarize()` | `summarize that` | Summarize current transcript |
| `spoaken.noise(on)` | `noise on` | Enable noise suppression |
| `spoaken.noise(off)` | `noise off` | Disable noise suppression |
| `spoaken.status()` | `what mode` | Print current engine and settings to console |
| `spoaken.help()` | `what can you do` | Print all commands to console |

---

## Update and Repair Window

Open from the main GUI gear button, or run standalone:

```bash
~/Spoaken/venv/bin/python -m spoaken.control.update
```

### Sections

**Python Packages**: Table of every dependency showing installed version versus latest. Columns show a status icon: checkmark for up-to-date, up-arrow for upgrade available, X for missing. Buttons: Update All, Repair (reinstall all regardless of version), Check (refresh table without installing).

**Model Installer**: Download or re-download Vosk models (small, standard, gigaspeech) and trigger a Whisper model download for any supported model size.

**T5 Model Selector**: Switch between T5 grammar models. The selected model ID is written to `spoaken_config.json` immediately.

**Spoaken Update**: Pull the latest application version from GitHub. Uses `git pull` if a `.git` directory exists, falls back to downloading the main ZIP and extracting files otherwise. Config files and user data are preserved during update.

**System Info**: Platform, Python version, RAM, disk space, and current package versions.

---

## Module Reference

### `spoaken.core.config`

Loads `spoaken_config.json`, merges with built-in defaults, and exports all settings as module-level constants. Zero import overhead on repeated imports (constants are evaluated once at module load).

```python
from spoaken.core.config import WHISPER_MODEL, VOSK_ENABLED, GRAMMAR_ENABLED, ENGINE_MODE
```

### `spoaken.core.engine`

`TranscriptionModel` loads and manages Vosk and Whisper models. `AudioPipeline` is a singleton that processes every audio block. Module-level functions are the public API for the controller:

```python
from spoaken.core.engine import (
    process_audio,       # run audio block through the pipeline
    audio_gate,          # VAD gate — returns block or None
    reset_vad,           # reset VAD state between sessions
    translate_text,      # online translation via deep-translator
    configure_pipeline,  # live pipeline parameter update
    apply_hardware_preset,
)
```

`_config_write_lock` is a module-level threading lock shared by all modules that write `spoaken_config.json`. Import it to prevent concurrent write corruption.

### `spoaken.core.vad`

Voice Activity Detection. Reads settings from the main config at import time (zero extra I/O). Saves changes back to the main config via the same candidate-path logic as the controller.

### `spoaken.control.controller`

`TranscriptionController` owns the audio capture loop, Vosk and Whisper decode loops, LLM and grammar background workers, session recovery, and all GUI-facing callbacks. One instance is created at startup and lives for the entire application lifetime.

### `spoaken.processing.summarize_router`

Single entry point for all summarization. Call `summarize(text)` — the router selects the best available backend with automatic fallback.

```python
from spoaken.processing.summarize_router import summarize, is_llm_available
print(is_llm_available())     # True if Ollama is running
result = summarize("long transcript...")
```

### `spoaken.system.paths`

Resolves all runtime paths from config. Always import paths from here rather than constructing them manually.

```python
from spoaken.system.paths import WHISPER_DIR, VOSK_DIR, LOG_DIR, ASSETS_DIR, ROOT_DIR
```

### `spoaken.system.environ`

Non-blocking CPU and RAM monitor. Uses a background 1-Hz sampler so `can_run_llm()` never blocks the audio thread.

```python
from spoaken.system.environ import SysEnviron
env = SysEnviron(log_fn=print)
env.benchmark()              # quick hardware assessment
env.can_run_llm()            # O(1), non-blocking
env.get_llm_chunk_budget()   # words-per-chunk based on RAM
```

### `spoaken.system.session_recovery`

```python
from spoaken.system.session_recovery import SessionRecovery
recovery = SessionRecovery(controller, interval_s=60)
recovery.start()                          # begin auto-save loop
recovery.stop()                           # clean stop, deletes recovery file
segments = recovery.check_restore()       # returns list[str] or None
recovery.discard()                        # delete without restoring
age = recovery.recovery_file_age_minutes()
```

### `spoaken.network.chat`

Compatibility re-export layer. Import `ChatServer` and `SSEServer` from here rather than directly from `lan` or `online` to keep the rest of the codebase stable if implementations change.

---

## Platform Notes

### Windows

- winget is required for FFmpeg auto-install (Windows 10 21H2+ or App Installer from Microsoft Store)
- GPU support uses CUDA 12.1 wheels — install the CUDA toolkit before enabling `gpu = true`
- `pywin32` and `pywinauto` are installed automatically for window writing

### macOS

- **Accessibility permission required before first launch**: System Settings > Privacy and Security > Accessibility > add your Terminal app and enable the toggle. Without this, Spoaken cannot type into other windows.
- Homebrew is installed automatically if missing
- Window writing uses `pyautogui` only — no wmctrl or xdotool dependency

### Linux (X11)

- `wmctrl` and `xdotool` are installed for full window targeting support
- Fully tested on Ubuntu 20.04+, Fedora 38+, Arch

### Linux (Wayland)

- `xdotool` and `wmctrl` do not function under Wayland sessions
- Spoaken falls back to `pyautogui` automatically and logs a warning at startup
- Window targeting by title is unavailable under Wayland
- For full Window Writer support, log out and select the Xorg session at the display manager

---

## Troubleshooting

**"venv not found"**  
The venv was not created. Re-run `./install.sh` or `python install.py --interactive`.

**"webrtcvad build failed"**  
```bash
# Ubuntu/Debian
sudo apt install python3-dev build-essential
# Fedora
sudo dnf install python3-devel gcc
# Skip VAD entirely:
./install.sh --no-vad
```

**"No module named pip" inside new venv (Debian/Ubuntu)**  
The installer handles this automatically via `get-pip.py` bootstrap. If it still fails:
```bash
sudo apt install python3.11-venv   # match your exact Python version
```

**Whisper model not downloading**  
Whisper downloads from HuggingFace Hub on first launch. Behind a proxy:
```bash
export HTTPS_PROXY=http://proxy:port
~/Spoaken/run.sh
```

**High CPU usage**  
Switch to Vosk (substantially lower CPU than Whisper), disable grammar correction until needed, or lower `audio_lookahead_buffer` in config.

**Transcript appears empty or no text transcribed**  
Check OS microphone permissions (macOS Privacy settings, Windows microphone access). Open Mic Setup and confirm the level bar moves when speaking. Try a different audio preset for your hardware type.

**LAN chat not connecting**  
Both machines must be on the same subnet. Check firewall rules for port 55300 (or your configured port). Verify the auth token matches on both sides.

**T5 model download fails offline**  
Set `offline_mode = true` in config to prevent download attempts. The model can be manually placed in `~/.cache/huggingface/hub/` and Spoaken will find it automatically.

**Spoaken exits immediately on Windows**  
Run from a Command Prompt rather than double-clicking so error messages are visible. Check that the venv Python exists at `<install_dir>\venv\Scripts\python.exe`.

---

## CLI Reference

### install.py

```
python install.py                       interactive guided setup (default)
python install.py --interactive         explicit interactive mode
python install.py --config my.json      re-run from a saved config file
python install.py --online-only         add online packages to an existing offline install
python install.py --vosk-only           re-download or update the Vosk model only
python install.py --no-vad              skip webrtcvad (no C compiler available)
python install.py --offline             force offline install
python install.py --online              force online install
```

Hidden flags for CI and scripted use (accepted but not shown in --help):

```
python install.py --llm --noise --chat --offline
python install.py --translation
```

### install.sh

```bash
./install.sh             standard install — forwards all flags to install.py --interactive
./install.sh --no-vad    skip webrtcvad
./install.sh --offline   force offline
```

All flags are forwarded through to `install.py`.

### run.sh

```bash
~/Spoaken/run.sh
```

`run.sh` activates the venv and runs `python -m spoaken`. It is always copied to `<install_dir>` by the installer. Any arguments are passed through to the application.

---

*Spoaken v2.1.1 — https://github.com/daltyn-maker/Spoaken*
