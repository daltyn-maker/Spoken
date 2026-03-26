"""
spoaken_mic_config.py (ENHANCED with Audio Processing Controls)
─────────────────────────────────────────────────────────────────
Microphone configuration and audio tuning panel for Spoaken.

ENHANCEMENTS ADDED:
  • AGC (Automatic Gain Control) controls - target RMS, max gain
  • Dynamic Compression controls - threshold, ratio, makeup gain
  • Hardware Preset buttons - one-click configuration for mic types
  • Live processing indicator - shows which processors are active

Features
────────
  • Live RMS level meter  — see what the mic is picking up in real time
  • VAD gate indicator    — SPEECH / SILENCE badge updates live
  • VAD aggressiveness / min-speech / silence-gap sliders
  • EQ / frequency profile presets
  • Noise profile capture
  • noisereduce strength slider
  • NEW: AGC controls - normalize quiet speakers
  • NEW: Compression controls - prevent clipping
  • NEW: Hardware presets - one-click mic type configuration
  • "Record 5 s test" — runs current settings through Vosk AND Whisper
"""

from __future__ import annotations

import json
import sys
import threading
import numpy as np
from pathlib import Path

import customtkinter as ctk
import sounddevice as sd

# ── Config file (same spoaken_config.json used by core/config.py) ─────────────
_HERE = Path(__file__).parent
_ROOT = _HERE.parent.parent
_CONFIG_CANDIDATES = [
    _ROOT / "spoaken_config.json",
    _HERE.parent / "spoaken_config.json",
    Path.home() / ".spoaken" / "config.json",
]

_MIC_PANEL_DEFAULTS = {
    "mic_device": -1,
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
    "current_preset": "budget_usb",
}

def _find_config_path() -> Path | None:
    for p in _CONFIG_CANDIDATES:
        if p.exists():
            return p
    return None

def _load_mic_panel_config() -> dict:
    path = _find_config_path()
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return {**_MIC_PANEL_DEFAULTS, **data.get("mic_panel", {})}
        except Exception as e:
            print(f"[MicConfig Warning]: {path}: {e}", file=sys.stderr)
    return _MIC_PANEL_DEFAULTS.copy()

def _save_mic_panel_config(mic_panel: dict) -> None:
    path = _find_config_path()
    if path is None:
        # Fall back to project root
        path = _ROOT / "spoaken_config.json"
    try:
        existing: dict = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        existing["mic_panel"] = mic_panel
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"[MicConfig Warning]: Could not save config: {e}", file=sys.stderr)

# ── Theme (matches Spoaken palette) ──────────────────────────────────────────
BG_DEEP        = "#060c1a"
BG_PANEL       = "#0a1128"
BG_CARD        = "#0d1735"
BG_INPUT       = "#0c1636"
BORDER         = "#1a2d60"
BORDER_ACTIVE  = "#2545a8"

COLOR_MAIN     = "#00bdff"
COLOR_TEAL     = "#00e5cc"
COLOR_DIM      = "#2a6080"
COLOR_WARN     = "#d4aa00"
COLOR_OK       = "#24c45e"
COLOR_ERR      = "#e03535"
COLOR_CONSOLE  = "#007bff"

FONT_TITLE = ("Segoe UI Semibold", 13)
FONT_UI    = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO  = ("Courier New", 10)

_SR = 16000


# ─────────────────────────────────────────────────────────────────────────────
class MicConfigPanel(ctk.CTkToplevel):

    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self._ctrl = controller

        # ── Load persisted config ─────────────────────────────────────────────
        self._cfg = _load_mic_panel_config()

        self.title("Spoaken — Microphone Setup")
        self.geometry("660x800")          # Increased height for new sections
        self.minsize(560, 480)
        self.configure(fg_color=BG_DEEP)
        self.resizable(True, True)

        # Runtime state
        self._stream        = None
        self._stream_lock   = threading.Lock()
        self._meter_rms     = 0.0
        self._gate_open     = False
        self._noise_profile = self._cfg.get("noise_profile")
        self._capturing     = False
        self._testing       = False

        # Own VAD for the live meter (separate from the global one in connect)
        try:
            from spoaken.core.vad import VAD
            self._vad = VAD()
        except Exception:
            self._vad = None

        self._build_ui()
        self.after(50,  self._centre)
        self.after(300, self._start_meter)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────────────────────────────────────────────────────────────────
    # UI construction
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Window layout:
        #   row 0 — fixed header banner
        #   row 1 — scrollable frame (cards + log)
        #   row 2 — fixed bottom action bar (Apply / Reset / Close)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)   # only scroll area stretches
        self.grid_rowconfigure(2, weight=0)   # action bar stays at bottom

        self._build_header()   # row 0 — fixed

        # ── Scrollable content area ────────────────────────────────────────────
        self._scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color="#1a2d60",
            scrollbar_button_hover_color="#2545a8",
            corner_radius=0,
        )
        self._scroll_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self._scroll_frame.grid_columnconfigure(0, weight=1)

        # All cards are placed inside _scroll_frame
        self._build_device_row()     # card 0
        self._build_meter_section()  # card 1
        self._build_hardware_presets()  # card 2 - NEW
        self._build_agc_section()    # card 3 - NEW
        self._build_comp_section()   # card 4 - NEW
        self._build_vad_section()    # card 5
        self._build_eq_section()     # card 6
        self._build_nr_section()     # card 7
        self._build_test_section()   # card 8
        self._build_log()            # card 9

        # ── Fixed bottom action bar (always visible, never scrolled) ──────────
        self._build_actions()        # row 2

    def _build_header(self):
        header_frame = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0)
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        # ── Logo icon ────────────────────────────────────────────────────────
        _logo_img = None
        try:
            from spoaken.system.paths import ART_DIR
            from PIL import Image
            for _name in ("logo.png", "logo.ico", "icon.png", "icon.ico"):
                _p = ART_DIR / _name
                if _p.exists():
                    _img = Image.open(_p).resize((32, 32), Image.LANCZOS)
                    _logo_img = ctk.CTkImage(light_image=_img, dark_image=_img, size=(32, 32))
                    break
        except Exception:
            pass

        if _logo_img:
            ctk.CTkLabel(
                header_frame, image=_logo_img, text="",
            ).grid(row=0, column=0, rowspan=2, padx=(14, 6), pady=(8, 8), sticky="w")
            col_start = 1
        else:
            col_start = 0

        ctk.CTkLabel(header_frame, text="Microphone Setup & Audio Tuning",
                     font=FONT_TITLE, text_color=COLOR_TEAL, anchor="w",
                     ).grid(row=0, column=col_start, padx=(0 if _logo_img else 16, 16),
                            pady=(12, 2), sticky="w")
        ctk.CTkLabel(header_frame,
                     text="Tune VAD, EQ, noise filtering, AGC, and compression for your environment",
                     font=FONT_SMALL, text_color=COLOR_DIM, anchor="w",
                     ).grid(row=1, column=col_start, padx=(0 if _logo_img else 16, 16),
                            pady=(0, 10), sticky="w")
        ctk.CTkFrame(header_frame, height=1, fg_color=BORDER).grid(
            row=2, column=0, columnspan=2, sticky="ew")

    # ── Device row ────────────────────────────────────────────────────────────

    def _build_device_row(self):
        f = self._card(1, "Microphone Device")
        f.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(f, text="Device", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=0, column=0, padx=(12, 6), pady=10, sticky="w")

        from spoaken.core.engine import list_input_devices
        devices   = list_input_devices()
        names     = ["[sys] System Default"] + [f"[{i}] {n}" for i, n in devices]

        self._cmb_device = ctk.CTkComboBox(
            f, values=names, font=FONT_SMALL, text_color=COLOR_MAIN,
            fg_color=BG_INPUT, border_color=BORDER, border_width=1,
            button_color=BORDER_ACTIVE, button_hover_color="#3a60c8",
            dropdown_fg_color=BG_CARD, dropdown_text_color=COLOR_MAIN,
            height=30, corner_radius=5,
            command=lambda _: None,
        )
        self._cmb_device.grid(row=0, column=1, padx=(0, 12), pady=10, sticky="ew")
        self._cmb_device.set(names[0])

    # ── NEW: Hardware Presets Section ─────────────────────────────────────────

    def _build_hardware_presets(self):
        f = self._card(2, "🎯 Hardware Presets (Quick Setup)")
        f.grid_columnconfigure((0, 1, 2, 3), weight=1)

        # Description
        desc = ctk.CTkLabel(
            f, 
            text="One-click configuration for your microphone type. Automatically sets AGC, compression, and EQ.",
            font=FONT_SMALL, text_color=COLOR_DIM, wraplength=600, justify="left"
        )
        desc.grid(row=0, column=0, columnspan=4, padx=12, pady=(8, 4), sticky="w")

        # Preset buttons
        presets = [
            ("clean", "🎙️ Studio/Podcast", "Minimal processing"),
            ("budget_usb", "💰 Budget USB", "Moderate processing"),
            ("headset", "🎮 Gaming Headset", "Aggressive processing"),
            ("laptop", "💻 Laptop Built-in", "Maximum processing"),
        ]

        for idx, (key, label, desc_text) in enumerate(presets):
            btn_frame = ctk.CTkFrame(f, fg_color=BG_INPUT, corner_radius=6, border_width=1, border_color=BORDER)
            btn_frame.grid(row=1, column=idx, padx=6, pady=(4, 12), sticky="ew")
            
            btn = ctk.CTkButton(
                btn_frame,
                text=label,
                font=FONT_SMALL,
                fg_color="transparent",
                hover_color=BORDER_ACTIVE,
                text_color=COLOR_MAIN,
                height=28,
                command=lambda k=key: self._apply_preset(k),
            )
            btn.pack(fill="x", padx=4, pady=(4, 2))
            
            desc_lbl = ctk.CTkLabel(
                btn_frame,
                text=desc_text,
                font=("Segoe UI", 8),
                text_color=COLOR_DIM,
            )
            desc_lbl.pack(pady=(0, 4))

        # Current preset indicator
        self._lbl_current_preset = ctk.CTkLabel(
            f,
            text=f"Current: {self._cfg.get('current_preset', 'budget_usb').replace('_', ' ').title()}",
            font=FONT_SMALL,
            text_color=COLOR_TEAL,
        )
        self._lbl_current_preset.grid(row=2, column=0, columnspan=4, padx=12, pady=(0, 8), sticky="w")

    def _apply_preset(self, preset_key: str):
        """Apply a hardware preset and update UI controls."""
        try:
            import spoaken.core.engine as _sc
            
            if preset_key not in _sc._HARDWARE_PRESETS:
                self._log(f"[Preset Error]: Unknown preset '{preset_key}'")
                return
            
            preset = _sc._HARDWARE_PRESETS[preset_key]
            
            # Apply preset to spoaken_connect module
            _sc.apply_hardware_preset(preset_key)
            
            # Update UI controls to reflect preset values
            config = _sc._mic_config
            
            # AGC
            self._agc_on.set(config.get("agc_enabled", True))
            self._sld_agc_target.set(config.get("agc_target_rms", 0.15))
            self._sld_agc_maxgain.set(config.get("agc_max_gain_db", 12.0))
            self._update_agc_labels()
            
            # Compression
            self._comp_on.set(config.get("comp_enabled", True))
            self._sld_comp_thresh.set(config.get("comp_threshold_db", -12.0))
            self._sld_comp_ratio.set(config.get("comp_ratio", 3.0))
            self._update_comp_labels()
            
            # EQ
            self._eq_var.set(config.get("eq_profile", "speech"))
            self._sld_hp.set(config.get("hp_cutoff", 80))
            self._on_eq_change()
            
            # NR
            self._nr_on.set(config.get("nr_enabled", False))
            
            # Update current preset label
            self._lbl_current_preset.configure(
                text=f"Current: {preset['name']}",
                text_color=COLOR_OK
            )

            # Track which preset is active so it survives Apply/reopen
            self._cfg["current_preset"] = preset_key

            self._log(f"[Preset]: Applied '{preset['name']}'")
            
        except Exception as exc:
            self._log(f"[Preset Error]: {exc}")

    # ── NEW: AGC Section ──────────────────────────────────────────────────────

    def _build_agc_section(self):
        f = self._card(3, "🔊 AGC (Automatic Gain Control)")
        f.grid_columnconfigure(1, weight=1)

        # Enable toggle
        self._agc_on = ctk.BooleanVar(value=self._cfg.get("agc_enabled", True))
        chk = ctk.CTkCheckBox(
            f, text="Enable AGC (normalizes quiet speakers)",
            variable=self._agc_on, font=FONT_SMALL,
            fg_color=COLOR_MAIN, hover_color=COLOR_TEAL,
            text_color=COLOR_MAIN, command=self._on_agc_toggle,
        )
        chk.grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        # Info label
        info = ctk.CTkLabel(
            f,
            text="Automatically adjusts volume for consistent loudness. Essential for budget microphones.",
            font=("Segoe UI", 9), text_color=COLOR_DIM, wraplength=600, justify="left",
        )
        info.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        # Target RMS
        ctk.CTkLabel(f, text="Target RMS", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=2, column=0, padx=(12, 6), pady=(0, 4), sticky="w")
        
        slider_frame = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame.grid(row=2, column=1, padx=(0, 12), pady=(0, 4), sticky="ew")
        slider_frame.grid_columnconfigure(0, weight=1)
        
        self._sld_agc_target = ctk.CTkSlider(
            slider_frame, from_=0.05, to=0.30, number_of_steps=50,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=self._on_agc_target_change,
        )
        self._sld_agc_target.set(self._cfg.get("agc_target_rms", 0.15))
        self._sld_agc_target.grid(row=0, column=0, sticky="ew")
        
        self._lbl_agc_target = ctk.CTkLabel(
            slider_frame, text=f"{self._cfg.get('agc_target_rms', 0.15):.2f}",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=50
        )
        self._lbl_agc_target.grid(row=0, column=1, padx=(8, 0))

        # Max Gain
        ctk.CTkLabel(f, text="Max Gain (dB)", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=3, column=0, padx=(12, 6), pady=(4, 12), sticky="w")
        
        slider_frame2 = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame2.grid(row=3, column=1, padx=(0, 12), pady=(4, 12), sticky="ew")
        slider_frame2.grid_columnconfigure(0, weight=1)
        
        self._sld_agc_maxgain = ctk.CTkSlider(
            slider_frame2, from_=3.0, to=24.0, number_of_steps=21,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=self._on_agc_maxgain_change,
        )
        self._sld_agc_maxgain.set(self._cfg.get("agc_max_gain_db", 12.0))
        self._sld_agc_maxgain.grid(row=0, column=0, sticky="ew")
        
        self._lbl_agc_maxgain = ctk.CTkLabel(
            slider_frame2, text=f"{int(self._cfg.get('agc_max_gain_db', 12.0))} dB",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=50
        )
        self._lbl_agc_maxgain.grid(row=0, column=1, padx=(8, 0))

    def _on_agc_toggle(self):
        enabled = self._agc_on.get()
        state = "normal" if enabled else "disabled"
        self._sld_agc_target.configure(state=state)
        self._sld_agc_maxgain.configure(state=state)
        
    def _on_agc_target_change(self, val):
        self._lbl_agc_target.configure(text=f"{val:.2f}")
        
    def _on_agc_maxgain_change(self, val):
        self._lbl_agc_maxgain.configure(text=f"{int(val)} dB")
        
    def _update_agc_labels(self):
        """Update AGC slider labels (used by preset application)."""
        self._lbl_agc_target.configure(text=f"{self._sld_agc_target.get():.2f}")
        self._lbl_agc_maxgain.configure(text=f"{int(self._sld_agc_maxgain.get())} dB")

    # ── NEW: Compression Section ──────────────────────────────────────────────

    def _build_comp_section(self):
        f = self._card(4, "🎚️ Dynamic Range Compression")
        f.grid_columnconfigure(1, weight=1)

        # Enable toggle
        self._comp_on = ctk.BooleanVar(value=self._cfg.get("comp_enabled", True))
        chk = ctk.CTkCheckBox(
            f, text="Enable Compression (prevents clipping)",
            variable=self._comp_on, font=FONT_SMALL,
            fg_color=COLOR_MAIN, hover_color=COLOR_TEAL,
            text_color=COLOR_MAIN, command=self._on_comp_toggle,
        )
        chk.grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        # Info label
        info = ctk.CTkLabel(
            f,
            text="Limits loud sounds (plosives, sudden movements) to prevent distortion. Use AFTER AGC.",
            font=("Segoe UI", 9), text_color=COLOR_DIM, wraplength=600, justify="left",
        )
        info.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="w")

        # Threshold
        ctk.CTkLabel(f, text="Threshold (dBFS)", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=2, column=0, padx=(12, 6), pady=(0, 4), sticky="w")
        
        slider_frame = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame.grid(row=2, column=1, padx=(0, 12), pady=(0, 4), sticky="ew")
        slider_frame.grid_columnconfigure(0, weight=1)
        
        self._sld_comp_thresh = ctk.CTkSlider(
            slider_frame, from_=-24.0, to=-3.0, number_of_steps=21,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=self._on_comp_thresh_change,
        )
        self._sld_comp_thresh.set(self._cfg.get("comp_threshold_db", -12.0))
        self._sld_comp_thresh.grid(row=0, column=0, sticky="ew")
        
        self._lbl_comp_thresh = ctk.CTkLabel(
            slider_frame, text=f"{int(self._cfg.get('comp_threshold_db', -12.0))} dB",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=60
        )
        self._lbl_comp_thresh.grid(row=0, column=1, padx=(8, 0))

        # Ratio
        ctk.CTkLabel(f, text="Ratio", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=3, column=0, padx=(12, 6), pady=(4, 12), sticky="w")
        
        slider_frame2 = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame2.grid(row=3, column=1, padx=(0, 12), pady=(4, 12), sticky="ew")
        slider_frame2.grid_columnconfigure(0, weight=1)
        
        self._sld_comp_ratio = ctk.CTkSlider(
            slider_frame2, from_=1.0, to=10.0, number_of_steps=18,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=self._on_comp_ratio_change,
        )
        self._sld_comp_ratio.set(self._cfg.get("comp_ratio", 3.0))
        self._sld_comp_ratio.grid(row=0, column=0, sticky="ew")
        
        self._lbl_comp_ratio = ctk.CTkLabel(
            slider_frame2, text=f"{self._cfg.get('comp_ratio', 3.0):.1f}:1",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=60
        )
        self._lbl_comp_ratio.grid(row=0, column=1, padx=(8, 0))

    def _on_comp_toggle(self):
        enabled = self._comp_on.get()
        state = "normal" if enabled else "disabled"
        self._sld_comp_thresh.configure(state=state)
        self._sld_comp_ratio.configure(state=state)
        
    def _on_comp_thresh_change(self, val):
        self._lbl_comp_thresh.configure(text=f"{int(val)} dB")
        
    def _on_comp_ratio_change(self, val):
        self._lbl_comp_ratio.configure(text=f"{val:.1f}:1")
        
    def _update_comp_labels(self):
        """Update compression slider labels (used by preset application)."""
        self._lbl_comp_thresh.configure(text=f"{int(self._sld_comp_thresh.get())} dB")
        self._lbl_comp_ratio.configure(text=f"{self._sld_comp_ratio.get():.1f}:1")

    # ── Meter section (unchanged except moved down) ──────────────────────────

    def _build_meter_section(self):
        f = self._card(5, "📊 Live Audio Monitor")
        f.grid_columnconfigure(0, weight=1)

        # RMS meter
        meter_row = ctk.CTkFrame(f, fg_color="transparent")
        meter_row.grid(row=0, column=0, padx=12, pady=(8, 2), sticky="ew")
        meter_row.grid_columnconfigure(0, weight=1)

        self._meter_bar = ctk.CTkProgressBar(
            meter_row, height=16, fg_color=BORDER, progress_color=COLOR_OK,
            corner_radius=8,
        )
        self._meter_bar.set(0.0)
        self._meter_bar.grid(row=0, column=0, sticky="ew")

        self._lbl_meter_val = ctk.CTkLabel(
            meter_row, text="0.000", font=FONT_MONO, text_color=COLOR_MAIN, width=60,
        )
        self._lbl_meter_val.grid(row=0, column=1, padx=(8, 0))

        # VAD gate
        gate_row = ctk.CTkFrame(f, fg_color="transparent")
        gate_row.grid(row=1, column=0, padx=12, pady=(4, 8), sticky="ew")
        gate_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(gate_row, text="VAD Gate:", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=0, column=0, sticky="w")
        
        self._lbl_gate = ctk.CTkLabel(
            gate_row, text="SILENCE", font=FONT_SMALL, text_color=COLOR_DIM,
            fg_color=BG_INPUT, corner_radius=4, width=80, height=24,
        )
        self._lbl_gate.grid(row=0, column=1, padx=(8, 0))

    # ── VAD section (renumbered to card 6) ────────────────────────────────────

    def _build_vad_section(self):
        f = self._card(6, "🎤 Voice Activity Detection (VAD)")
        f.grid_columnconfigure(1, weight=1)

        self._vad_on = ctk.BooleanVar(value=self._cfg.get("vad_enabled", True))
        chk = ctk.CTkCheckBox(
            f, text="Enable VAD gate", variable=self._vad_on, font=FONT_SMALL,
            fg_color=COLOR_MAIN, hover_color=COLOR_TEAL, text_color=COLOR_MAIN,
        )
        chk.grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        # Aggressiveness
        ctk.CTkLabel(f, text="Aggressiveness", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=1, column=0, padx=(12, 6), pady=(4, 0), sticky="w")
        
        slider_frame = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame.grid(row=1, column=1, padx=(0, 12), pady=(4, 0), sticky="ew")
        slider_frame.grid_columnconfigure(0, weight=1)
        
        sld_agg = ctk.CTkSlider(
            slider_frame, from_=0, to=3, number_of_steps=3,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=self._on_vad_agg_change,
        )
        sld_agg.set(self._cfg.get("vad_agg", 2))
        sld_agg.grid(row=0, column=0, sticky="ew")
        
        _agg_labels = ["0 (Off)", "1 (Low)", "2 (Normal)", "3 (High)"]
        self._lbl_vad_agg = ctk.CTkLabel(
            slider_frame,
            text=_agg_labels[min(int(self._cfg.get("vad_agg", 2)), 3)],
            font=FONT_SMALL, text_color=COLOR_MAIN, width=100
        )
        self._lbl_vad_agg.grid(row=0, column=1, padx=(8, 0))

        # Min speech
        ctk.CTkLabel(f, text="Min Speech Duration", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=2, column=0, padx=(12, 6), pady=(6, 0), sticky="w")
        
        slider_frame2 = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame2.grid(row=2, column=1, padx=(0, 12), pady=(6, 0), sticky="ew")
        slider_frame2.grid_columnconfigure(0, weight=1)
        
        sld_min = ctk.CTkSlider(
            slider_frame2, from_=50, to=500, number_of_steps=18,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=lambda v: self._lbl_min_speech.configure(text=f"{int(v)} ms"),
        )
        sld_min.set(self._cfg.get("min_speech", 200))
        sld_min.grid(row=0, column=0, sticky="ew")
        
        self._lbl_min_speech = ctk.CTkLabel(
            slider_frame2, text=f"{self._cfg.get('min_speech', 200)} ms",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=100
        )
        self._lbl_min_speech.grid(row=0, column=1, padx=(8, 0))

        # Silence gap
        ctk.CTkLabel(f, text="Silence Gap", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=3, column=0, padx=(12, 6), pady=(6, 12), sticky="w")
        
        slider_frame3 = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame3.grid(row=3, column=1, padx=(0, 12), pady=(6, 12), sticky="ew")
        slider_frame3.grid_columnconfigure(0, weight=1)
        
        sld_gap = ctk.CTkSlider(
            slider_frame3, from_=100, to=1500, number_of_steps=14,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=lambda v: self._lbl_silence_gap.configure(text=f"{int(v)} ms"),
        )
        sld_gap.set(self._cfg.get("silence_gap", 500))
        sld_gap.grid(row=0, column=0, sticky="ew")
        
        self._lbl_silence_gap = ctk.CTkLabel(
            slider_frame3, text=f"{self._cfg.get('silence_gap', 500)} ms",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=100
        )
        self._lbl_silence_gap.grid(row=0, column=1, padx=(8, 0))

        self._vad_sliders = [sld_agg, sld_min, sld_gap]

    def _on_vad_agg_change(self, val):
        labels = ["0 (Off)", "1 (Low)", "2 (Normal)", "3 (High)"]
        idx = int(round(val))
        self._lbl_vad_agg.configure(text=labels[idx])
        if self._vad:
            self._vad.set_aggressiveness(idx, save=False)

    # ── EQ section (renumbered to card 7) ─────────────────────────────────────

    def _build_eq_section(self):
        f = self._card(7, "🎛️ EQ / Frequency Profile")
        f.grid_columnconfigure(1, weight=1)

        self._eq_var = ctk.StringVar(value=self._cfg.get("eq_profile", "speech"))

        profiles = [
            ("flat", "Flat (no filter)"),
            ("speech", "Speech (80 Hz HP)"),
            ("aggressive", "Aggressive (100 Hz HP + notch)"),
            ("custom", "Custom"),
        ]

        for idx, (key, label) in enumerate(profiles):
            rb = ctk.CTkRadioButton(
                f, text=label, variable=self._eq_var, value=key,
                font=FONT_SMALL, text_color=COLOR_MAIN,
                fg_color=COLOR_MAIN, hover_color=COLOR_TEAL,
                command=self._on_eq_change,
            )
            rb.grid(row=idx, column=0, columnspan=2, padx=12, pady=(6 if idx == 0 else 2, 0), sticky="w")

        # Custom HP cutoff (only shown when custom selected)
        ctk.CTkLabel(f, text="Custom HP Cutoff", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=len(profiles), column=0, padx=(32, 6), pady=(4, 12), sticky="w")
        
        slider_frame = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame.grid(row=len(profiles), column=1, padx=(0, 12), pady=(4, 12), sticky="ew")
        slider_frame.grid_columnconfigure(0, weight=1)
        
        self._sld_hp = ctk.CTkSlider(
            slider_frame, from_=40, to=200, number_of_steps=32,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", state="disabled",
            command=lambda v: self._lbl_hp_val.configure(text=f"{int(v)} Hz"),
        )
        self._sld_hp.set(self._cfg.get("hp_cutoff", 80))
        self._sld_hp.grid(row=0, column=0, sticky="ew")
        
        self._lbl_hp_val = ctk.CTkLabel(
            slider_frame, text=f"{self._cfg.get('hp_cutoff', 80)} Hz",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=60
        )
        self._lbl_hp_val.grid(row=0, column=1, padx=(8, 0))

    def _on_eq_change(self):
        self._sld_hp.configure(state="normal" if self._eq_var.get() == "custom" else "disabled")

    # ── NR section (renumbered to card 8) ─────────────────────────────────────

    def _build_nr_section(self):
        f = self._card(8, "🔇 Noise Reduction")
        f.grid_columnconfigure(1, weight=1)

        self._nr_on = ctk.BooleanVar(value=self._cfg.get("nr_enabled", False))
        chk = ctk.CTkCheckBox(
            f, text="Enable noise reduction", variable=self._nr_on, font=FONT_SMALL,
            fg_color=COLOR_MAIN, hover_color=COLOR_TEAL, text_color=COLOR_MAIN,
        )
        chk.grid(row=0, column=0, columnspan=2, padx=12, pady=(8, 4), sticky="w")

        # Capture noise profile
        self._btn_cap = ctk.CTkButton(
            f, text="🎙️ Capture 2 s Noise Profile", font=FONT_SMALL,
            fg_color=BORDER_ACTIVE, hover_color="#3a60c8", text_color="#ffffff",
            height=30, corner_radius=6, command=self._capture_noise,
        )
        self._btn_cap.grid(row=1, column=0, columnspan=2, padx=12, pady=(4, 2), sticky="ew")

        _has_profile = self._noise_profile is not None
        self._lbl_cap_status = ctk.CTkLabel(
            f,
            text="Noise profile loaded ✓" if _has_profile else "No profile — using stationary estimation",
            font=FONT_SMALL,
            text_color=COLOR_OK if _has_profile else COLOR_DIM,
        )
        self._lbl_cap_status.grid(row=2, column=0, columnspan=2, padx=12, pady=(2, 6), sticky="w")

        # Strength
        ctk.CTkLabel(f, text="NR Strength", font=FONT_SMALL, text_color=COLOR_DIM,
                     ).grid(row=3, column=0, padx=(12, 6), pady=(0, 12), sticky="w")
        
        slider_frame = ctk.CTkFrame(f, fg_color="transparent")
        slider_frame.grid(row=3, column=1, padx=(0, 12), pady=(0, 12), sticky="ew")
        slider_frame.grid_columnconfigure(0, weight=1)
        
        self._sld_nr = ctk.CTkSlider(
            slider_frame, from_=0.0, to=1.0, number_of_steps=20,
            fg_color=BORDER, progress_color=COLOR_MAIN, button_color=COLOR_TEAL,
            button_hover_color="#00ffdd", command=lambda v: self._lbl_nr_val.configure(text=f"{v:.2f}"),
        )
        self._sld_nr.set(self._cfg.get("nr_strength", 0.75))
        self._sld_nr.grid(row=0, column=0, sticky="ew")
        
        self._lbl_nr_val = ctk.CTkLabel(
            slider_frame, text=f"{self._cfg.get('nr_strength', 0.75):.2f}",
            font=FONT_SMALL, text_color=COLOR_MAIN, width=60
        )
        self._lbl_nr_val.grid(row=0, column=1, padx=(8, 0))

    def _capture_noise(self):
        if self._capturing:
            return
        self._capturing = True
        self._btn_cap.configure(state="disabled", text="Recording…")
        self._lbl_cap_status.configure(text="Recording ambient noise…", text_color=COLOR_WARN)
        
        def _cap_thread():
            try:
                rec = sd.rec(int(_SR * 2), samplerate=_SR, channels=1, dtype='float32', blocking=True)
                self._noise_profile = rec.flatten()
                self.after(0, lambda: self._lbl_cap_status.configure(
                    text="Profile captured ✓", text_color=COLOR_OK
                ))
                self._log("[NR]: Noise profile captured (2 s)")
            except Exception as exc:
                self.after(0, lambda e=exc: self._lbl_cap_status.configure(
                    text=f"Capture failed: {e}", text_color=COLOR_ERR
                ))
                self._log(f"[NR Error]: {exc}")
            finally:
                self._capturing = False
                self.after(0, lambda: self._btn_cap.configure(state="normal", text="🎙️ Capture 2 s Noise Profile"))
        
        threading.Thread(target=_cap_thread, daemon=True).start()

    # ── Test section (renumbered to card 9) ───────────────────────────────────

    def _build_test_section(self):
        f = self._card(9, "🧪 Test & Verify")
        f.grid_columnconfigure(0, weight=1)

        self._btn_test = ctk.CTkButton(
            f, text="▶  Record 5 s test", font=FONT_UI,
            fg_color=COLOR_MAIN, hover_color=COLOR_TEAL, text_color="#ffffff",
            height=36, corner_radius=6, command=self._run_test,
        )
        self._btn_test.grid(row=0, column=0, padx=12, pady=(8, 4), sticky="ew")

        self._lbl_test_status = ctk.CTkLabel(
            f, text="Apply settings, then record a 5 s test to compare engines",
            font=FONT_SMALL, text_color=COLOR_DIM, wraplength=600, justify="center",
        )
        self._lbl_test_status.grid(row=1, column=0, padx=12, pady=(2, 12))

    def _run_test(self):
        if self._testing:
            return
        self._testing = True
        self._btn_test.configure(state="disabled", text="Recording 5 s…")
        self._lbl_test_status.configure(text="Recording…", text_color=COLOR_WARN)
        
        def _test_thread():
            try:
                rec = sd.rec(int(_SR * 5), samplerate=_SR, channels=1, dtype='int16', blocking=True)
                pcm = rec.flatten()
                
                # Apply current pipeline
                processed = self._apply_pipeline(pcm)
                pcm_bytes = processed.tobytes()
                
                # Run both engines
                self.after(0, lambda: self._lbl_test_status.configure(text="Transcribing with Vosk…", text_color=COLOR_WARN))
                vosk_text = self._run_vosk(pcm_bytes)
                
                self.after(0, lambda: self._lbl_test_status.configure(text="Transcribing with Whisper…", text_color=COLOR_WARN))
                whisper_text = self._run_whisper(pcm_bytes)
                
                vw = len(vosk_text.split())
                ww = len(whisper_text.split())
                
                self._log(f"[Test] Vosk ({vw} words): {vosk_text[:100]}")
                self._log(f"[Test] Whisper ({ww} words): {whisper_text[:100]}")
                
                def _upd():
                    self._lbl_test_status.configure(
                        text=f"Done — Vosk: {vw} words  ·  Whisper: {ww} words",
                        text_color=COLOR_OK if (vw + ww) > 0 else COLOR_WARN,
                    )
                self.after(0, _upd)

            except Exception as exc:
                self._log(f"[Test error]: {exc}")
                self.after(0, lambda e=exc: self._lbl_test_status.configure(
                    text=f"Error: {e}", text_color=COLOR_ERR,
                ))
            finally:
                self._testing = False
                self.after(0, lambda: self._btn_test.configure(
                    state="normal", text="▶  Record 5 s test",
                ))

        threading.Thread(target=_test_thread, daemon=True).start()

    def _apply_pipeline(self, pcm: np.ndarray) -> np.ndarray:
        """Apply current EQ + NR + AGC + Compression settings to a test buffer."""
        arr = pcm.astype(np.float32)
        
        # Convert to float [-1, 1]
        arr = arr / 32768.0
        
        # AGC (if enabled)
        if self._agc_on.get():
            try:
                import spoaken.core.engine as _sc
                target_rms = float(self._sld_agc_target.get())
                max_gain_db = float(self._sld_agc_maxgain.get())
                agc = _sc.SimpleAGC(target_rms=target_rms, max_gain_db=max_gain_db)
                arr = agc.process(arr)
            except Exception as exc:
                self._log(f"[AGC]: {exc}")
        
        # Compression (if enabled)
        if self._comp_on.get():
            try:
                import spoaken.core.engine as _sc
                threshold_db = float(self._sld_comp_thresh.get())
                ratio = float(self._sld_comp_ratio.get())
                comp = _sc.SimpleDynamicCompressor(threshold_db=threshold_db, ratio=ratio)
                arr = comp.process(arr)
            except Exception as exc:
                self._log(f"[Compression]: {exc}")
        
        # EQ
        profile = self._eq_var.get()
        if profile != "flat":
            try:
                from scipy.signal import butter, sosfilt, iirnotch, tf2sos
                if profile in ("speech", "custom"):
                    cutoff = float(self._sld_hp.get()) if profile == "custom" else 80.0
                    sos = butter(4, cutoff / (_SR / 2), btype="high", output="sos")
                    arr = sosfilt(sos, arr)
                elif profile == "aggressive":
                    sos = butter(5, 100.0 / (_SR / 2), btype="high", output="sos")
                    arr = sosfilt(sos, arr)
                    for freq in (60.0, 120.0):
                        b, a = iirnotch(freq, 30.0, _SR)
                        arr = sosfilt(tf2sos(b, a), arr)
            except ImportError:
                self._log("[EQ]: scipy not installed — pip install scipy")
            except Exception as exc:
                self._log(f"[EQ]: {exc}")

        # Noise Reduction
        if self._nr_on.get():
            try:
                import noisereduce as nr_
                strength = float(self._sld_nr.get())
                arr_int16 = (arr * 32768.0).astype(np.float32)
                if self._noise_profile is not None:
                    yn = (self._noise_profile * 32768.0).astype(np.float32)
                    arr_int16 = nr_.reduce_noise(y=arr_int16, y_noise=yn, sr=_SR,
                                           prop_decrease=strength, stationary=True)
                else:
                    arr_int16 = nr_.reduce_noise(y=arr_int16, sr=_SR,
                                           prop_decrease=strength, stationary=True)
                arr = arr_int16 / 32768.0
            except ImportError:
                self._log("[NR]: noisereduce not installed — pip install noisereduce")
            except Exception as exc:
                self._log(f"[NR]: {exc}")

        # Clip and convert back
        return np.clip(arr * 32768.0, -32768, 32767).astype(np.int16)

    def _run_vosk(self, pcm_bytes: bytes) -> str:
        try:
            from spoaken.core.engine import VoskModel, KaldiRecognizer, _vosk_ok, _resolve_vosk
            from spoaken.core.config import QUICK_VOSK_MODEL
            import json as _json
            if not _vosk_ok:
                return "(vosk not installed)"
            model = VoskModel(_resolve_vosk(QUICK_VOSK_MODEL))
            rec   = KaldiRecognizer(model, _SR)
            rec.SetWords(True)
            for i in range(0, len(pcm_bytes), 3200):
                rec.AcceptWaveform(pcm_bytes[i:i+3200])
            return _json.loads(rec.FinalResult()).get("text", "").strip()
        except Exception as exc:
            return f"(error: {exc})"

    def _run_whisper(self, pcm_bytes: bytes) -> str:
        try:
            from spoaken.core.engine import WhisperModel, _whisper_ok, _resolve_compute_type
            from spoaken.core.config import WHISPER_MODEL, GPU_ENABLED, WHISPER_COMPUTE
            from spoaken.system.paths import WHISPER_DIR
            if not _whisper_ok:
                return "(faster-whisper not installed)"
            device       = "cuda" if GPU_ENABLED else "cpu"
            compute_type = _resolve_compute_type(WHISPER_COMPUTE, GPU_ENABLED)
            model        = WhisperModel(WHISPER_MODEL, device=device,
                                        compute_type=compute_type,
                                        download_root=str(WHISPER_DIR))
            arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            segs, _ = model.transcribe(arr, beam_size=3, vad_filter=True)
            return " ".join(s.text.strip() for s in segs).strip()
        except Exception as exc:
            return f"(error: {exc})"

    # ── Log (renumbered to card 10) ───────────────────────────────────────────

    def _build_log(self):
        f = self._card(10, "📝 Activity Log")
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)

        self._log_box = ctk.CTkTextbox(
            f, height=120, font=FONT_MONO, text_color=COLOR_CONSOLE,
            fg_color=BG_INPUT, border_width=1, border_color=BORDER,
            corner_radius=6, wrap="word",
        )
        self._log_box.grid(row=0, column=0, padx=12, pady=(8, 12), sticky="nsew")
        self._log_box.insert("1.0", "[Ready] Configure settings and press Apply\n")
        self._log_box.configure(state="disabled")

    # ── Actions (Apply / Reset / Close) ───────────────────────────────────────

    def _build_actions(self):
        bar = ctk.CTkFrame(self, fg_color=BG_PANEL, corner_radius=0, height=60)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkFrame(bar, height=1, fg_color=BORDER).grid(
            row=0, column=0, columnspan=3, sticky="ew")

        ctk.CTkButton(
            bar, text="✓  Apply", font=FONT_UI, fg_color=COLOR_OK,
            hover_color="#20aa50", text_color="#ffffff", height=38,
            corner_radius=6, command=self._apply,
        ).grid(row=1, column=0, padx=(16, 8), pady=10, sticky="ew")

        ctk.CTkButton(
            bar, text="↻  Reset Defaults", font=FONT_UI, fg_color=BORDER_ACTIVE,
            hover_color="#3a60c8", text_color="#ffffff", height=38,
            corner_radius=6, command=self._reset,
        ).grid(row=1, column=1, padx=8, pady=10, sticky="ew")

        ctk.CTkButton(
            bar, text="✕  Close", font=FONT_UI, fg_color=BG_INPUT,
            hover_color=BORDER, text_color=COLOR_DIM, height=38,
            corner_radius=6, border_width=1, border_color=BORDER,
            command=self._on_close,
        ).grid(row=1, column=2, padx=(8, 16), pady=10, sticky="ew")

    # ─────────────────────────────────────────────────────────────────────────
    # Apply / Reset
    # ─────────────────────────────────────────────────────────────────────────

    def _apply(self):
        """Write all settings to spoaken_connect._mic_config and persist to config.json."""
        dev = self._dev_index()
        if self._ctrl:
            try:
                self._ctrl.set_mic_device(dev)
            except Exception:
                pass

        # Build the canonical mic_panel dict from current UI state
        mic_panel = {
            "mic_device"       : dev,
            "vad_enabled"      : self._vad_on.get(),
            "vad_agg"          : int(round(self._vad_sliders[0].get())),
            "min_speech"       : int(round(self._vad_sliders[1].get() / 50) * 50),
            "silence_gap"      : int(round(self._vad_sliders[2].get() / 100) * 100),
            "eq_profile"       : self._eq_var.get(),
            "hp_cutoff"        : int(self._sld_hp.get()),
            "nr_enabled"       : self._nr_on.get(),
            "nr_strength"      : round(float(self._sld_nr.get()), 2),
            "noise_profile"    : self._noise_profile,
            "agc_enabled"      : self._agc_on.get(),
            "agc_target_rms"   : float(self._sld_agc_target.get()),
            "agc_max_gain_db"  : float(self._sld_agc_maxgain.get()),
            "comp_enabled"     : self._comp_on.get(),
            "comp_threshold_db": float(self._sld_comp_thresh.get()),
            "comp_ratio"       : float(self._sld_comp_ratio.get()),
            "comp_makeup_gain_db": self._cfg.get("comp_makeup_gain_db", 3.0),
            "current_preset"   : self._cfg.get("current_preset", "budget_usb"),
        }

        # Keep self._cfg in sync
        self._cfg.update(mic_panel)

        # ── Persist to config.json (single write) ────────────────────────────
        try:
            _save_mic_panel_config(mic_panel)
        except Exception as exc:
            self._log(f"[Save warning]: {exc}")

        # Push to engine module
        try:
            import spoaken.core.engine as _sc
            _sc._mic_config.update(mic_panel)

            # Recreate processors with new settings
            _sc._agc = _sc.SimpleAGC(
                target_rms=mic_panel["agc_target_rms"],
                max_gain_db=mic_panel["agc_max_gain_db"],
            )
            _sc._compressor = _sc.SimpleDynamicCompressor(
                threshold_db=mic_panel["comp_threshold_db"],
                ratio=mic_panel["comp_ratio"],
                makeup_gain_db=mic_panel["comp_makeup_gain_db"],
            )

            # Re-configure the global VAD singleton
            # Batch all set_* calls with save=False → single disk write at end
            if _sc._global_vad is not None:
                _sc._global_vad.set_aggressiveness(mic_panel["vad_agg"],  save=False)
                _sc._global_vad.set_min_speech(mic_panel["min_speech"],    save=False)
                _sc._global_vad.set_silence_gap(mic_panel["silence_gap"], save=False)
                _sc._global_vad.save_config()   # single disk write

            self._log(
                f"[Apply]: device={dev}  VAD={'on' if mic_panel['vad_enabled'] else 'off'}"
                f"/agg={mic_panel['vad_agg']}  "
                f"EQ={mic_panel['eq_profile']}  "
                f"NR={'on' if mic_panel['nr_enabled'] else 'off'}  "
                f"AGC={'on' if mic_panel['agc_enabled'] else 'off'}  "
                f"Comp={'on' if mic_panel['comp_enabled'] else 'off'}"
            )
        except Exception as exc:
            self._log(f"[Apply error]: {exc}")

        # Toggle noise suppression flag in controller
        if self._ctrl:
            try:
                self._ctrl.toggle_noise_suppression(self._nr_on.get())
            except Exception:
                pass

    def _reset(self):
        self._vad_on.set(True)
        self._vad_sliders[0].set(2);  self._on_vad_agg_change(2)
        self._vad_sliders[1].set(200); self._lbl_min_speech.configure(text="200 ms")
        self._vad_sliders[2].set(500); self._lbl_silence_gap.configure(text="500 ms")
        self._eq_var.set("speech");    self._on_eq_change()
        self._nr_on.set(False)
        self._sld_nr.set(0.75);        self._lbl_nr_val.configure(text="0.75")
        self._noise_profile = None
        self._lbl_cap_status.configure(
            text="No profile — using stationary estimation", text_color=COLOR_DIM,
        )

        # Reset AGC
        self._agc_on.set(True)
        self._sld_agc_target.set(0.15)
        self._sld_agc_maxgain.set(12.0)
        self._update_agc_labels()

        # Reset Compression
        self._comp_on.set(True)
        self._sld_comp_thresh.set(-12.0)
        self._sld_comp_ratio.set(3.0)
        self._update_comp_labels()

        # Reset preset label
        self._lbl_current_preset.configure(
            text="Current: Budget USB (default)",
            text_color=COLOR_TEAL
        )

        # Persist the reset values to config.json
        self._cfg = _MIC_PANEL_DEFAULTS.copy()
        try:
            _save_mic_panel_config(self._cfg)
        except Exception as exc:
            self._log(f"[Save warning]: {exc}")

        self._log("[Reset]: defaults restored and saved to config.json")

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _card(self, row: int, title: str) -> ctk.CTkFrame:
        container = ctk.CTkFrame(self._scroll_frame, fg_color="transparent")
        container.grid(row=row, column=0, sticky="ew", padx=16, pady=8)
        container.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=8, height=36)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_propagate(False)

        ctk.CTkLabel(header, text=title, font=FONT_TITLE, text_color=COLOR_TEAL, anchor="w",
                     ).grid(row=0, column=0, padx=12, sticky="w")

        content = ctk.CTkFrame(container, fg_color=BG_CARD, corner_radius=8)
        content.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        content.grid_columnconfigure(0, weight=1)

        return content

    def _dev_index(self) -> int:
        sel = self._cmb_device.get()
        if sel.startswith("[sys]"):
            return -1
        try:
            return int(sel.split("]")[0].split("[")[1])
        except Exception:
            return -1

    # ─────────────────────────────────────────────────────────────────────────
    # Live meter
    # ─────────────────────────────────────────────────────────────────────────

    def _start_meter(self):
        if self._stream is not None:
            return
        
        def _callback(indata, frames, time_info, status):
            arr = indata[:, 0] if indata.ndim > 1 else indata
            self._meter_rms = float(np.sqrt(np.mean(arr ** 2)))
            
            if self._vad:
                pcm = (arr * 32768).astype(np.int16).tobytes()
                result = self._vad.process(pcm)
                self._gate_open = (result is not None)
        
        try:
            with self._stream_lock:
                self._stream = sd.InputStream(
                    samplerate=_SR, channels=1, dtype='float32',
                    callback=_callback, blocksize=512,
                )
                self._stream.start()
            self._update_meter()
        except Exception as exc:
            self._log(f"[Meter Error]: {exc}")

    def _update_meter(self):
        if not self.winfo_exists():
            return
        
        rms = self._meter_rms
        self._meter_bar.set(min(rms * 4, 1.0))
        self._lbl_meter_val.configure(text=f"{rms:.3f}")
        
        if self._gate_open:
            self._lbl_gate.configure(text="SPEECH", text_color=COLOR_OK, fg_color=COLOR_OK + "20")
        else:
            self._lbl_gate.configure(text="SILENCE", text_color=COLOR_DIM, fg_color=BG_INPUT)
        
        self.after(50, self._update_meter)

    def _stop_meter(self):
        with self._stream_lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    # ─────────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        def _ins():
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
        if threading.current_thread() is threading.main_thread():
            _ins()
        else:
            try:
                self.after(0, _ins)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._stop_meter()
        if self.winfo_exists():
            self.destroy()

    def _centre(self):
        try:
            sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
            w  = self.winfo_width();       h  = self.winfo_height()
            self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
        except Exception:
            pass
