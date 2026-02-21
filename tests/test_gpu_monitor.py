"""Unit tests for GPU monitor."""

import pytest

from lmstudio_tui.gpu import GPUMetrics, GPUMonitor


class TestGPUMonitor:
    """Test GPU monitor functionality."""

    def test_init(self):
        """Test monitor initializes without crashing."""
        monitor = GPUMonitor()
        assert monitor is not None

    def test_start_no_crash(self):
        """Test start() does not crash regardless of GPU presence."""
        monitor = GPUMonitor()
        result = monitor.start()
        assert isinstance(result, bool)
        if result:
            monitor.shutdown()

    def test_get_metrics_before_start(self):
        """Test get_metrics() raises error if start() not called."""
        monitor = GPUMonitor()
        with pytest.raises(RuntimeError):
            monitor.get_metrics()

    def test_shutdown_without_start(self):
        """Test shutdown() safe to call without start()."""
        monitor = GPUMonitor()
        monitor.shutdown()


class TestGPUMonitorWithGPU:
    """Test GPU monitor when GPU is present."""

    @pytest.fixture
    def monitor(self):
        """Create and start monitor if GPU available."""
        mon = GPUMonitor()
        if not mon.start():
            pytest.skip("No NVIDIA GPU available")
        yield mon
        mon.shutdown()

    def test_get_metrics_returns_data(self, monitor):
        """Test get_metrics returns data when GPU available."""
        metrics = monitor.get_metrics()
        assert isinstance(metrics, list)
        assert len(metrics) > 0
        for m in metrics:
            assert isinstance(m, GPUMetrics)

    def test_gpu_id_valid(self, monitor):
        """Test GPU IDs are valid."""
        metrics = monitor.get_metrics()
        for i, m in enumerate(metrics):
            assert m.gpu_id == i
            assert m.gpu_id >= 0

    def test_name_present(self, monitor):
        """Test GPU names are present."""
        metrics = monitor.get_metrics()
        for m in metrics:
            assert m.name
            assert isinstance(m.name, str)
            assert len(m.name) > 0

    def test_utilization_in_range(self, monitor):
        """Test utilization is 0-100%."""
        metrics = monitor.get_metrics()
        for m in metrics:
            assert 0 <= m.utilization <= 100

    def test_vram_non_negative(self, monitor):
        """Test VRAM values are non-negative."""
        metrics = monitor.get_metrics()
        for m in metrics:
            assert m.vram_used >= 0
            assert m.vram_total >= 0
            assert m.vram_used <= m.vram_total

    def test_temperature_non_negative(self, monitor):
        """Test temperature is non-negative."""
        metrics = monitor.get_metrics()
        for m in metrics:
            assert m.temperature >= 0

    def test_power_draw_non_negative(self, monitor):
        """Test power draw is non-negative."""
        metrics = monitor.get_metrics()
        for m in metrics:
            assert m.power_draw >= 0


class TestGPUMetrics:
    """Test GPUMetrics dataclass."""

    def test_creation(self):
        """Test GPUMetrics can be created."""
        m = GPUMetrics(
            gpu_id=0,
            name="Test GPU",
            utilization=50,
            vram_used=4096,
            vram_total=8192,
            temperature=65,
            power_draw=150.5,
        )
        assert m.gpu_id == 0
        assert m.name == "Test GPU"
        assert m.utilization == 50
        assert m.vram_used == 4096
        assert m.vram_total == 8192
        assert m.temperature == 65
        assert m.power_draw == 150.5
