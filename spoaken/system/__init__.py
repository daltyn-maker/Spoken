"""
system - System Utilities and Monitoring
=========================================

Crash logging, system monitoring, path resolution, and audio configuration.
"""

from spoaken.system.crashlog import CrashLogger, setup_global_exception_handler, log_crashes
from spoaken.system.environ import SysEnviron
from spoaken.system.paths import (
    SPOAKEN_DIR,
    ROOT_DIR,
    WHISPER_DIR,
    VOSK_DIR,
    ASSETS_DIR,
    LOG_DIR,
)

__all__ = [
    # Crash logging
    "CrashLogger",
    "setup_global_exception_handler",
    "log_crashes",
    # System monitoring
    "SysEnviron",
    # Paths
    "SPOAKEN_DIR",
    "ROOT_DIR",
    "WHISPER_DIR",
    "VOSK_DIR",
    "ASSETS_DIR",
    "LOG_DIR",
]
