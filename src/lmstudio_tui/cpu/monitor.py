"""CPU and system RAM monitoring using psutil."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False


@dataclass
class CPUMetrics:
    """System-level CPU and RAM metrics, including LM Studio process usage."""

    cpu_model: str          # CPU model name
    ram_free_gb: float      # Free (available) system RAM in GB
    ram_lmstudio_gb: float  # RSS RAM consumed by LM Studio processes in GB
    cpu_utilization: float  # Overall system CPU utilisation %
    cpu_lmstudio_pct: float # CPU % consumed by LM Studio processes


class CPUMonitor:
    """Collect CPU and RAM metrics via psutil.

    Call ``start()`` once at app startup; call ``get_metrics()`` to poll.
    Returns False from ``start()`` if psutil is unavailable so callers can
    fall back gracefully, matching the GPUMonitor pattern.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._cpu_model = "Unknown CPU"

    def start(self) -> bool:
        """Initialise the monitor.  Returns False if psutil is not installed."""
        if not _PSUTIL_AVAILABLE:
            return False
        self._cpu_model = self._detect_cpu_model()
        # Prime the per-process CPU % counters (first call always returns 0.0)
        psutil.cpu_percent(interval=None)
        for _ in psutil.process_iter(["cpu_percent"]):
            pass
        self._initialized = True
        return True

    def get_metrics(self) -> CPUMetrics:
        """Return a snapshot of CPU and RAM metrics.

        Raises:
            RuntimeError: If ``start()`` has not been called successfully.
        """
        if not self._initialized:
            raise RuntimeError("CPUMonitor not started")

        vm = psutil.virtual_memory()
        ram_free_gb = vm.available / (1024 ** 3)
        cpu_util = psutil.cpu_percent(interval=None)

        lms_ram_bytes = 0
        lms_cpu_pct = 0.0
        for proc in psutil.process_iter(["name", "cmdline", "memory_info", "cpu_percent"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmdline = " ".join(proc.info["cmdline"] or []).lower()
                if "lmstudio" in name or (name == "lms") or "/.lmstudio/" in cmdline:
                    mem = proc.info["memory_info"]
                    if mem:
                        lms_ram_bytes += mem.rss
                    lms_cpu_pct += proc.info["cpu_percent"] or 0.0
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        return CPUMetrics(
            cpu_model=self._cpu_model,
            ram_free_gb=ram_free_gb,
            ram_lmstudio_gb=lms_ram_bytes / (1024 ** 3),
            cpu_utilization=cpu_util,
            cpu_lmstudio_pct=lms_cpu_pct,
        )

    def shutdown(self) -> None:
        """No-op; provided for API symmetry with GPUMonitor."""
        self._initialized = False

    @staticmethod
    def _detect_cpu_model() -> str:
        """Read CPU model from /proc/cpuinfo, falling back to platform.processor()."""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        model = line.split(":", 1)[1].strip()
                        # Collapse whitespace
                        return re.sub(r"\s+", " ", model)
        except Exception:
            pass
        try:
            import platform
            return platform.processor() or "Unknown CPU"
        except Exception:
            return "Unknown CPU"
