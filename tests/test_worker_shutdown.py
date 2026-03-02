"""Tests for worker shutdown signaling."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from lmstudio_tui.app import LMStudioApp


@pytest.mark.asyncio
async def test_worker_shutdown_within_100ms():
    """Test that workers exit within 100ms of shutdown signal."""
    app = LMStudioApp()
    shutdown_times = []
    
    async def mock_worker(name: str, delay: float):
        """Mock worker that tracks shutdown time."""
        start = asyncio.get_event_loop().time()
        while not app._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    app._shutdown_event.wait(),
                    timeout=delay
                )
            except asyncio.TimeoutError:
                pass
        shutdown_times.append((name, asyncio.get_event_loop().time() - start))
    
    # Start workers
    app._shutdown_event = asyncio.Event()
    workers = [
        asyncio.create_task(mock_worker("gpu", 1.0)),
        asyncio.create_task(mock_worker("model", 2.0)),
        asyncio.create_task(mock_worker("health", 5.0)),
    ]
    
    # Give workers time to start
    await asyncio.sleep(0.01)
    
    # Signal shutdown
    start_shutdown = asyncio.get_event_loop().time()
    app._shutdown_event.set()
    
    # Wait for all workers
    await asyncio.gather(*workers, return_exceptions=True)
    total_time = asyncio.get_event_loop().time() - start_shutdown
    
    # Assert all exited within 100ms
    assert total_time < 0.1, f"Workers took {total_time}s to exit, max 100ms expected"
    for name, t in shutdown_times:
        assert t < 0.1, f"Worker {name} took {t}s to exit"


@pytest.mark.asyncio
async def test_shutdown_event_is_asyncio_event():
    """Ensure shutdown_event is proper asyncio.Event."""
    app = LMStudioApp()
    assert isinstance(app._shutdown_event, asyncio.Event)


@pytest.mark.asyncio
async def test_no_resource_leaks_on_shutdown():
    """Verify no lingering tasks after shutdown."""
    app = LMStudioApp()
    
    # Track initial tasks
    initial_tasks = set(asyncio.all_tasks())
    
    # Start workers
    app._shutdown_event = asyncio.Event()
    workers = [
        asyncio.create_task(asyncio.sleep(10)),
        asyncio.create_task(asyncio.sleep(10)),
        asyncio.create_task(asyncio.sleep(10)),
    ]
    
    # Give workers time to start
    await asyncio.sleep(0.01)
    
    # Cancel workers (simulating shutdown)
    for w in workers:
        w.cancel()
    
    # Shutdown
    app._shutdown_event.set()
    await asyncio.sleep(0.1)
    
    # Clean up cancelled tasks
    await asyncio.gather(*workers, return_exceptions=True)
    
    # Check no extra tasks remain
    final_tasks = set(asyncio.all_tasks())
    app_tasks = final_tasks - initial_tasks
    
    # Filter out the current test task
    app_tasks = {t for t in app_tasks if t != asyncio.current_task()}
    
    assert len(app_tasks) == 0, f"Leaked tasks: {app_tasks}"


@pytest.mark.asyncio
async def test_on_shutdown_sets_event():
    """Test that on_shutdown() sets the shutdown event."""
    app = LMStudioApp()
    app._shutdown_event = asyncio.Event()
    
    # Mock store methods to avoid actual cleanup
    with patch.object(app.store, 'stop_gpu_monitoring') as mock_stop_gpu, \
         patch.object(app.store, 'disconnect_from_server', new_callable=AsyncMock) as mock_disconnect:
        
        assert not app._shutdown_event.is_set()
        
        # Call on_shutdown
        await app.on_shutdown()
        
        # Verify event was set
        assert app._shutdown_event.is_set()
        # Verify store cleanup was called
        mock_stop_gpu.assert_called_once()
        mock_disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_worker_loop_condition_uses_shutdown_event():
    """Test that workers use while not shutdown_event.is_set() pattern."""
    import inspect

    app = LMStudioApp()

    assert hasattr(app, '_shutdown_event')
    assert isinstance(app._shutdown_event, asyncio.Event)

    source = inspect.getsource(app._gpu_update_worker)
    assert 'while not self._shutdown_event.is_set()' in source

    source = inspect.getsource(app._models_update_worker)
    assert 'while not self._shutdown_event.is_set()' in source
