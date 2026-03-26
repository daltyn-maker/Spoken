"""
system/environ.py
─────────────────
O(1) CPU monitoring and auto model switching.
System environment monitoring for resource management.
"""

import threading
import time

try:
    import psutil

    _PSUTIL_OK = True
except ImportError:
    psutil = None
    _PSUTIL_OK = False

from collections import deque


class SysEnviron:
    def __init__(self, log_fn=print):
        self._log = log_fn
        self._benchmark_done = False
        self._llm_chunk_budget_val = 80

        # Rolling average with O(1) update via running sum
        self._cpu_history = deque(maxlen=10)
        self._cpu_running_sum = 0.0
        self._high_cpu_count = 0
        self._model_switched = False

        # Latest non-blocking CPU reading (updated by background sampler)
        self._last_cpu = 0.0
        self._sampler_started = False
        self._sampler_stop = threading.Event()  # set to stop the sampler thread

    # ── Background CPU sampler ────────────────────────────────────────────────
    def _start_sampler(self):
        """Start a 1-Hz background thread that refreshes cpu_percent."""
        if self._sampler_started or not _PSUTIL_OK:
            return
        self._sampler_started = True

        def _run():
            while not self._sampler_stop.is_set():
                try:
                    # interval=1 blocks the *sampler* thread, not the caller
                    self._last_cpu = psutil.cpu_percent(interval=1)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def stop(self):
        """Stop the background sampler thread."""
        self._sampler_stop.set()

    # ── Benchmark ─────────────────────────────────────────────────────────────
    def benchmark(self, log_fn=None):
        """Quick benchmark — O(1), starts background sampler."""
        self._start_sampler()
        try:
            cpu_count = psutil.cpu_count() if _PSUTIL_OK else 1
            ram_gb = psutil.virtual_memory().total / (1024**3) if _PSUTIL_OK else 4.0

            if ram_gb < 4:
                self._llm_chunk_budget_val = 40
            elif ram_gb < 8:
                self._llm_chunk_budget_val = 80
            else:
                self._llm_chunk_budget_val = 150

            self._benchmark_done = True
            if log_fn:
                log_fn(
                    f"[SysEnviron]: {cpu_count} cores, "
                    f"{ram_gb:.1f}GB RAM, chunk={self._llm_chunk_budget_val}"
                )
        except Exception:
            self._benchmark_done = True
            self._llm_chunk_budget_val = 80

    def get_llm_chunk_budget(self) -> int:
        """O(1) lookup."""
        return self._llm_chunk_budget_val

    def can_run_llm(self) -> bool:
        """
        O(1) non-blocking CPU check with rolling average.
        Reads self._last_cpu (set by background sampler) — never blocks.
        """
        if not _PSUTIL_OK:
            return True

        cpu = self._last_cpu

        # O(1) rolling-sum update
        if len(self._cpu_history) == self._cpu_history.maxlen:
            # Subtract the value being evicted before appending
            self._cpu_running_sum -= self._cpu_history[0]
        self._cpu_history.append(cpu)
        self._cpu_running_sum += cpu

        avg_cpu = self._cpu_running_sum / len(self._cpu_history)

        if avg_cpu > 50:
            self._high_cpu_count += 1
            if self._high_cpu_count >= 5 and not self._model_switched:
                self._log(
                    "[CPU]: High load detected — consider switching to lighter model"
                )
                self._model_switched = True
            return False
        else:
            self._high_cpu_count = 0
            self._model_switched = False
            return True

    def check_and_prompt_resources(self, controller) -> bool:
        """Non-blocking resource check."""
        if not _PSUTIL_OK:
            return False
        try:
            cpu = self._last_cpu  # non-blocking read
            if cpu > 70:
                self._log(
                    "[Warning]: CPU >70% — close background apps or switch to Vosk-only"
                )
                return True
        except Exception:
            pass
        return False
