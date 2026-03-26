"""
system/crashlog.py
──────────────────
Comprehensive crash logging and error reporting for Spoaken.

Features:
  • Automatic crash log creation with full stack traces
  • System information capture (OS, Python version, RAM, CPU)
  • Recent log excerpts included in crash reports
  • User-friendly error dialog with option to view/copy crash log
  • Logs saved to ~/Spoaken/logs/crashes/ with timestamps
"""

import sys
import os
import traceback
import platform
import datetime
from pathlib import Path

# ── Try to import psutil for system info ─────────────────────────────────────
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False


class CrashLogger:
    """Handles crash logging and error reporting for Spoaken."""

    def __init__(self, app_name: str = "Spoaken"):
        self.app_name = app_name
        self.crash_dir = self._get_crash_dir()
        self.crash_dir.mkdir(parents=True, exist_ok=True)

    def _get_crash_dir(self) -> Path:
        """Get crash log directory path."""
        try:
            from spoaken.system.paths import LOG_DIR

            return LOG_DIR / "crashes"
        except ImportError:
            # Fallback if paths.py not available
            return Path.home() / self.app_name / "logs" / "crashes"

    def _get_system_info(self) -> str:
        """Gather system information for crash report."""
        lines = []

        # Python version
        lines.append(f"Python: {sys.version}")
        lines.append(f"Platform: {platform.platform()}")
        lines.append(f"Architecture: {platform.machine()}")

        # System resources
        if PSUTIL_AVAILABLE:
            try:
                mem = psutil.virtual_memory()
                lines.append(
                    f"RAM: {mem.total / (1024**3):.2f} GB total, "
                    f"{mem.available / (1024**3):.2f} GB available"
                )
                lines.append(
                    f"CPU: {psutil.cpu_count()} cores @ "
                    f"{psutil.cpu_percent(interval=0.1)}% usage"
                )
            except Exception:
                pass

        # Environment
        lines.append(f"Working Directory: {os.getcwd()}")
        lines.append(f"Executable: {sys.executable}")

        return "\n".join(lines)

    def _get_recent_logs(self, max_lines: int = 50) -> str:
        """Get recent log entries from main log file."""
        try:
            from spoaken.system.paths import LOG_DIR

            # The single session log is always "log.txt" (see controller.py LOG_FILE).
            # Fall back to any *.log or *.txt file if the canonical name is absent.
            candidates = [
                LOG_DIR / "log.txt",          # standard path written by controller
            ]
            candidates += sorted(
                LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            candidates += sorted(
                LOG_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
            )

            log_file = next((p for p in candidates if p.exists()), None)
            if log_file is None:
                return "[No log files found]"

            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                recent = lines[-max_lines:] if len(lines) > max_lines else lines
                return "".join(recent)
        except Exception as e:
            return f"[Could not read logs: {e}]"

    def _get_installed_packages(self) -> str:
        """Get list of installed Python packages (key dependencies)."""
        packages = []
        key_modules = [
            "vosk",
            "faster_whisper",
            "customtkinter",
            "numpy",
            "sounddevice",
            "websockets",
            "psutil",
            "transformers",
        ]

        for module_name in key_modules:
            try:
                mod = __import__(module_name)
                version = getattr(mod, "__version__", "unknown")
                packages.append(f"{module_name}: {version}")
            except ImportError:
                packages.append(f"{module_name}: NOT INSTALLED")
            except Exception as e:
                packages.append(f"{module_name}: error - {e}")

        return "\n".join(packages) if packages else "[Could not determine packages]"

    def write_crash_log(
        self,
        exception: Exception,
        exc_type: type,
        exc_traceback,
        context: str = "Application Startup",
    ) -> Path:
        """
        Write comprehensive crash log to file.

        Returns:
            Path to the created crash log file
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"crash_{timestamp}.log"
        crash_file = self.crash_dir / filename

        # Build crash report
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append(f"{self.app_name} CRASH REPORT")
        report_lines.append("=" * 80)
        report_lines.append(
            f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        report_lines.append(f"Context: {context}")
        report_lines.append("")

        # Exception info
        report_lines.append("─" * 80)
        report_lines.append("EXCEPTION")
        report_lines.append("─" * 80)
        report_lines.append(f"Type: {exc_type.__name__}")
        report_lines.append(f"Message: {str(exception)}")
        report_lines.append("")

        # Full traceback
        report_lines.append("─" * 80)
        report_lines.append("STACK TRACE")
        report_lines.append("─" * 80)
        tb_lines = traceback.format_exception(exc_type, exception, exc_traceback)
        report_lines.extend(tb_lines)
        report_lines.append("")

        # System information
        report_lines.append("─" * 80)
        report_lines.append("SYSTEM INFORMATION")
        report_lines.append("─" * 80)
        report_lines.append(self._get_system_info())
        report_lines.append("")

        # Installed packages
        report_lines.append("─" * 80)
        report_lines.append("INSTALLED PACKAGES")
        report_lines.append("─" * 80)
        report_lines.append(self._get_installed_packages())
        report_lines.append("")

        # Recent logs
        report_lines.append("─" * 80)
        report_lines.append("RECENT LOGS (last 50 lines)")
        report_lines.append("─" * 80)
        report_lines.append(self._get_recent_logs())
        report_lines.append("")

        report_lines.append("=" * 80)
        report_lines.append("END OF CRASH REPORT")
        report_lines.append("=" * 80)

        # Write to file
        crash_file.write_text("\n".join(report_lines), encoding="utf-8")

        return crash_file

    def show_crash_dialog(self, crash_file: Path):
        """Show user-friendly crash dialog with option to view crash log."""
        try:
            import tkinter as tk
            from tkinter import messagebox, scrolledtext

            # Create error dialog
            root = tk.Tk()
            root.withdraw()  # Hide main window

            # Simple message box first
            result = messagebox.askyesno(
                f"{self.app_name} - Fatal Error",
                f"{self.app_name} has encountered a fatal error and needs to close.\n\n"
                f"A crash log has been saved to:\n{crash_file}\n\n"
                "Would you like to view the crash log?",
                icon="error",
            )

            if result:
                # Show crash log in window
                viewer = tk.Toplevel()
                viewer.title(f"{self.app_name} - Crash Log")
                viewer.geometry("800x600")

                # Text widget with scrollbar
                text = scrolledtext.ScrolledText(viewer, wrap=tk.WORD, font=("Consolas", 9))
                text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

                # Load crash log
                crash_content = crash_file.read_text(encoding="utf-8")
                text.insert(tk.END, crash_content)
                text.config(state=tk.DISABLED)  # Read-only

                # Copy button
                def copy_to_clipboard():
                    viewer.clipboard_clear()
                    viewer.clipboard_append(crash_content)
                    messagebox.showinfo("Copied", "Crash log copied to clipboard")

                btn_frame = tk.Frame(viewer)
                btn_frame.pack(fill=tk.X, padx=5, pady=5)

                tk.Button(btn_frame, text="Copy to Clipboard", command=copy_to_clipboard).pack(
                    side=tk.LEFT, padx=5
                )

                tk.Button(btn_frame, text="Close", command=viewer.destroy).pack(
                    side=tk.RIGHT, padx=5
                )

                viewer.mainloop()

            root.destroy()

        except Exception:
            # If GUI fails, just print location
            print(f"\n{'=' * 80}", file=sys.stderr)
            print(f"CRASH LOG SAVED: {crash_file}", file=sys.stderr)
            print(f"{'=' * 80}\n", file=sys.stderr)


# ── Global exception handler ──────────────────────────────────────────────────


def setup_global_exception_handler(app_name: str = "Spoaken"):
    """
    Set up global exception handler to catch and log all unhandled exceptions.
    Call this at the very start of your application.
    """
    crash_logger = CrashLogger(app_name)

    def exception_handler(exc_type, exc_value, exc_traceback):
        """Handle uncaught exceptions."""
        # Don't log KeyboardInterrupt
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        # Write crash log
        crash_file = crash_logger.write_crash_log(
            exc_value, exc_type, exc_traceback, context="Unhandled Exception"
        )

        # Print to stderr
        print(f"\n{'=' * 80}", file=sys.stderr)
        print("FATAL ERROR - Crash log saved to:", file=sys.stderr)
        print(f"{crash_file}", file=sys.stderr)
        print(f"{'=' * 80}\n", file=sys.stderr)

        # Print traceback to stderr
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)

        # Show GUI dialog if possible
        try:
            crash_logger.show_crash_dialog(crash_file)
        except Exception:
            pass  # GUI failed, already printed to stderr

    # Install handler
    sys.excepthook = exception_handler

    return crash_logger


# ── Convenience decorator ──────────────────────────────────────────────────────


def log_crashes(context: str = "Function Execution"):
    """
    Decorator to catch and log crashes in specific functions.

    Usage:
        @log_crashes("Model Initialization")
        def load_model():
            ...
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                crash_logger = CrashLogger()
                crash_file = crash_logger.write_crash_log(
                    e, type(e), sys.exc_info()[2], context=f"{context} - {func.__name__}"
                )
                print(f"[Crash Log]: {crash_file}", file=sys.stderr)
                raise  # Re-raise after logging

        return wrapper

    return decorator
