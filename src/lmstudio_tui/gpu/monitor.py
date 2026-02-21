"""GPU monitoring implementation using PyNVML."""

from contextlib import suppress
from dataclasses import dataclass

import pynvml


@dataclass
class GPUMetrics:
    """Metrics for a single GPU."""

    gpu_id: int
    name: str
    utilization: int  # 0-100%
    vram_used: int  # MB
    vram_total: int  # MB
    temperature: int  # °C
    power_draw: float  # Watts


class GPUMonitor:
    """Monitor NVIDIA GPUs using NVML."""

    def __init__(self) -> None:
        """Initialize the GPU monitor."""
        self._initialized = False
        self._gpu_count = 0

    def start(self) -> bool:
        """Initialize NVML and detect GPUs.

        Returns:
            True if NVIDIA GPUs are present and NVML initialized successfully.
            False if no NVIDIA GPUs are present or NVML initialization failed.
        """
        try:
            pynvml.nvmlInit()
            self._gpu_count = pynvml.nvmlDeviceGetCount()
            if self._gpu_count == 0:
                # No GPUs found, shutdown NVML
                pynvml.nvmlShutdown()
                return False
            self._initialized = True
            return True
        except (pynvml.NVMLError, Exception):
            # NVML initialization failed (no NVIDIA driver, etc.)
            return False

    def get_metrics(self) -> list[GPUMetrics]:
        """Get current metrics for all GPUs.

        Returns:
            List of GPUMetrics for each detected GPU.

        Raises:
            RuntimeError: If monitor has not been started or no GPUs available.
        """
        if not self._initialized:
            raise RuntimeError("GPU monitor not started or no GPUs available")

        metrics: list[GPUMetrics] = []

        for gpu_id in range(self._gpu_count):
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_id)

                # Get GPU name
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8")

                # Get utilization
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_util = utilization.gpu

                # Get memory info
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                vram_used = mem_info.used // (1024**2)
                vram_total = mem_info.total // (1024**2)

                # Get temperature
                try:
                    temperature = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                except pynvml.NVMLError:
                    temperature = 0

                # Get power draw
                try:
                    power_draw = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                except pynvml.NVMLError:
                    power_draw = 0.0

                metrics.append(
                    GPUMetrics(
                        gpu_id=gpu_id,
                        name=name,
                        utilization=gpu_util,
                        vram_used=vram_used,
                        vram_total=vram_total,
                        temperature=temperature,
                        power_draw=power_draw,
                    )
                )
            except pynvml.NVMLError:
                # Skip this GPU if we can't get its metrics
                continue

        return metrics

    def shutdown(self) -> None:
        """Cleanup NVML resources."""
        if self._initialized:
            with suppress(pynvml.NVMLError):
                pynvml.nvmlShutdown()
            self._initialized = False
            self._gpu_count = 0

    def __enter__(self) -> "GPUMonitor":
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.shutdown()
