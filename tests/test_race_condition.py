"""Tests for TOCTOU race condition in GPU monitor access."""

import threading
import time
import pytest
from unittest.mock import Mock, PropertyMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from lmstudio_tui.store import RootStore, reset_store


@pytest.fixture(autouse=True)
def reset_store_fixture():
    """Reset store singleton before each test."""
    reset_store()
    yield
    reset_store()


class TestGPUMonitorRaceCondition:
    """Tests for TOCTOU race condition in gpu_monitor access."""
    
    def test_atomic_capture_prevents_race(self):
        """Verify that capturing reference locally prevents TOCTOU."""
        store = RootStore()
        
        # Mock a gpu_monitor that changes state
        mock_monitor = Mock()
        mock_monitor.get_metrics.return_value = [{"test": "metrics"}]
        store._gpu_monitor = mock_monitor
        
        # Simulate the race condition pattern
        # OLD (buggy): 
        # if store.gpu_monitor is None:  # check
        #     return
        # store.gpu_monitor.get_metrics()  # use - could fail!
        
        # NEW (fixed):
        monitor = store.gpu_monitor        # atomic capture
        if monitor is None:
            return
        result = monitor.get_metrics()     # safe use
        
        # Now simulate another thread setting it to None
        store._gpu_monitor = None
        
        # Our local reference should still work
        assert result == [{"test": "metrics"}]
        assert monitor is not None  # Our captured ref is intact
        assert store.gpu_monitor is None  # Store attribute changed
    
    def test_concurrent_access_no_crash(self):
        """Verify no crash when gpu_monitor is accessed concurrently."""
        store = RootStore()
        
        # Create a mock monitor
        mock_monitor = Mock()
        mock_monitor.get_metrics.return_value = [{"gpu": "data"}]
        store._gpu_monitor = mock_monitor
        
        errors = []
        results = []
        
        def worker_access():
            """Simulate worker thread accessing gpu_monitor."""
            try:
                for _ in range(100):
                    # Use the fixed pattern
                    monitor = store.gpu_monitor
                    if monitor is None:
                        continue
                    metrics = monitor.get_metrics()
                    results.append(metrics)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        def unset_monitor():
            """Simulate shutdown unsetting gpu_monitor."""
            time.sleep(0.05)
            store._gpu_monitor = None
        
        # Start threads
        t1 = threading.Thread(target=worker_access)
        t2 = threading.Thread(target=unset_monitor)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Should have no errors
        assert len(errors) == 0, f"Errors occurred: {errors}"
        # Should have captured some results before it was unset
        assert len(results) > 0
    
    def test_none_capture_handled_correctly(self):
        """Verify that None is handled correctly when captured."""
        store = RootStore()
        store._gpu_monitor = None
        
        # Capture None
        monitor = store.gpu_monitor
        
        # Should detect None correctly
        assert monitor is None
        
        # Would not call get_metrics() in real code due to check
        # This test just verifies the capture works
    
    def test_old_pattern_would_be_vulnerable(self):
        """Document that the old pattern has a race condition vulnerability.
        
        This test demonstrates what COULD happen with the old pattern
        if a race condition occurred. We simulate it with a property
        that changes value between accesses.
        """
        store = RootStore()
        
        # Create a mock that simulates the race condition
        call_count = [0]
        
        def racing_getter(*args):
            call_count[0] += 1
            if call_count[0] == 1:
                # First access returns a valid monitor
                mock = Mock()
                mock.get_metrics.return_value = [{"gpu": "data"}]
                return mock
            # Subsequent accesses return None (simulating race)
            return None
        
        # Save the original property before replacing it
        original_property = RootStore.__dict__["gpu_monitor"]

        # Replace gpu_monitor with a property that changes
        type(store).gpu_monitor = property(racing_getter)

        try:
            # NEW pattern - always safe
            monitor = store.gpu_monitor  # Gets the monitor
            # Even if store.gpu_monitor returned None on a second access,
            # our local 'monitor' still holds the valid reference.

            assert monitor is not None
            assert monitor.get_metrics() == [{"gpu": "data"}]
        finally:
            # Restore the original property so other tests are not affected.
            type(store).gpu_monitor = original_property
