"""Tests for the RootStore state management."""

import pytest
from pathlib import Path

from lmstudio_tui.store import RootStore, get_store, reset_store, ReactiveVar
from lmstudio_tui.config import AppConfig, GPUConfig, ServerConfig
from lmstudio_tui.gpu.monitor import GPUMetrics
from lmstudio_tui.api.client import ModelInfo


class TestReactiveVar:
    """Tests for the ReactiveVar helper class."""

    def test_initial_value(self):
        """ReactiveVar stores initial value."""
        var = ReactiveVar(42)
        assert var.value == 42

    def test_value_change(self):
        """Setting value updates it."""
        var = ReactiveVar(0)
        var.value = 10
        assert var.value == 10

    def test_watch_called_on_change(self):
        """Watchers are called when value changes."""
        var = ReactiveVar(0)
        changes = []

        def watcher(old, new):
            changes.append((old, new))

        var.watch(watcher)
        var.value = 5

        assert len(changes) == 1
        assert changes[0] == (0, 5)

    def test_watch_not_called_on_same_value(self):
        """Watchers not called when value stays the same."""
        var = ReactiveVar(5)
        calls = []

        var.watch(lambda old, new: calls.append(1))
        var.value = 5  # Same value

        assert len(calls) == 0

    def test_unwatch(self):
        """Unwatch stops receiving notifications."""
        var = ReactiveVar(0)
        calls = []

        unwatch = var.watch(lambda old, new: calls.append(1))
        var.value = 1
        assert len(calls) == 1

        unwatch()
        var.value = 2
        assert len(calls) == 1  # No new call


class TestRootStoreSingleton:
    """Tests for RootStore singleton pattern."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        reset_store()

    def test_singleton_returns_same_instance(self):
        """Multiple calls return the same instance."""
        store1 = get_store()
        store2 = get_store()
        store3 = RootStore()

        assert store1 is store2
        assert store2 is store3
        assert isinstance(store1, RootStore)

    def test_singleton_after_reset(self):
        """Reset creates new instance on next access."""
        store1 = get_store()
        reset_store()
        store2 = get_store()

        assert store1 is not store2
        assert isinstance(store2, RootStore)

    def test_state_initialized(self):
        """Store state is properly initialized."""
        store = get_store()
        # Verify state container exists and has all expected fields
        assert hasattr(store, '_state')
        assert hasattr(store._state, 'config')
        assert hasattr(store._state, 'gpu_metrics')


class TestRootStoreReactiveFields:
    """Tests for reactive field initialization and access."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        reset_store()

    def test_config_initial_value(self):
        """Config has default AppConfig."""
        store = get_store()
        assert isinstance(store.config.value, AppConfig)
        assert isinstance(store.config.value.server, ServerConfig)
        assert isinstance(store.config.value.gpu, GPUConfig)

    def test_gpu_metrics_initial_value(self):
        """GPU metrics starts as empty list."""
        store = get_store()
        assert store.gpu_metrics.value == []

    def test_gpu_error_initial_value(self):
        """GPU error starts as None."""
        store = get_store()
        assert store.gpu_error.value is None

    def test_models_initial_value(self):
        """Models starts as empty list."""
        store = get_store()
        assert store.models.value == []

    def test_active_model_initial_value(self):
        """Active model starts as None."""
        store = get_store()
        assert store.active_model.value is None

    def test_models_error_initial_value(self):
        """Models error starts as None."""
        store = get_store()
        assert store.models_error.value is None

    def test_server_connected_initial_value(self):
        """Server connected starts as False."""
        store = get_store()
        assert store.server_connected.value is False

    def test_last_error_initial_value(self):
        """Last error starts as None."""
        store = get_store()
        assert store.last_error.value is None

    def test_reactive_notification(self):
        """Setting reactive value notifies watchers."""
        store = get_store()
        changes = []

        store.gpu_metrics.watch(lambda old, new: changes.append(len(new)))
        store.gpu_metrics.value = [GPUMetrics(0, "Test", 50, 1000, 8000, 70, 150.0)]

        assert len(changes) == 1
        assert changes[0] == 1


class TestRootStoreConfigMethods:
    """Tests for configuration loading and saving."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        reset_store()

    def test_load_config_with_none_uses_defaults(self):
        """Loading config with None path uses defaults."""
        store = get_store()
        store.load_config(None)

        assert store.config.value.server.host == "localhost"
        assert store.config.value.server.port == 1234

    def test_load_config_with_path(self, tmp_path):
        """Loading config from file works."""
        config_file = tmp_path / "test_config.toml"
        config_file.write_text("""
[server]
host = "custom.host"
port = 9999
""")

        store = get_store()
        store.load_config(config_file)

        assert store.config.value.server.host == "custom.host"
        assert store.config.value.server.port == 9999

    def test_save_config_creates_file(self, tmp_path):
        """Saving config creates file."""
        config_file = tmp_path / "saved_config.toml"

        store = get_store()
        store.save_config(config_file)

        assert config_file.exists()
        content = config_file.read_text()
        assert "[server]" in content
        assert "[gpu]" in content

    def test_save_and_reload_roundtrip(self, tmp_path):
        """Save and reload preserves config values."""
        config_file = tmp_path / "roundtrip.toml"

        store = get_store()
        store.config.value.server.host = "test.host"
        store.config.value.server.port = 5555
        store.save_config(config_file)

        # Reset and reload
        reset_store()
        store2 = get_store()
        store2.load_config(config_file)

        assert store2.config.value.server.host == "test.host"
        assert store2.config.value.server.port == 5555


class TestRootStoreGPUOperations:
    """Tests for GPU monitoring operations."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        store = get_store()
        store.stop_gpu_monitoring()
        reset_store()

    def test_start_gpu_monitoring_without_gpu(self):
        """Starting GPU monitoring without NVIDIA GPUs returns False."""
        store = get_store()
        # On systems without NVIDIA GPUs, this should return False
        result = store.start_gpu_monitoring()
        # We can't assert the result since it depends on the system
        # but we can assert it returns a boolean
        assert isinstance(result, bool)

    def test_stop_gpu_monitoring_when_not_started(self):
        """Stopping GPU monitoring when not started is safe."""
        store = get_store()
        # Should not raise
        store.stop_gpu_monitoring()
        assert store.gpu_monitor is None

    def test_double_start_gpu_monitoring(self):
        """Starting GPU monitoring twice is handled gracefully."""
        store = get_store()
        result1 = store.start_gpu_monitoring()
        result2 = store.start_gpu_monitoring()
        # Second call should return True (monitoring already started)
        assert isinstance(result2, bool)


class TestRootStoreAPIOperations:
    """Tests for API client operations."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        store = get_store()
        store.disconnect_from_server()
        reset_store()

    def test_connect_to_server_with_defaults(self):
        """Connecting with default config attempts connection."""
        store = get_store()
        # This will likely fail to connect since no server is running
        # but it should not raise an exception
        result = store.connect_to_server()
        assert isinstance(result, bool)

    def test_disconnect_when_not_connected(self):
        """Disconnecting when not connected is safe."""
        store = get_store()
        # Should not raise
        store.disconnect_from_server()
        assert store.api_client is None
        assert store.server_connected.value is False


class TestRootStoreModelManagement:
    """Tests for model management methods."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        reset_store()

    def test_set_active_model(self):
        """Setting active model updates the field."""
        store = get_store()
        store.set_active_model("model-123")
        assert store.active_model.value == "model-123"

    def test_set_active_model_to_none(self):
        """Setting active model to None clears it."""
        store = get_store()
        store.set_active_model("model-123")
        store.set_active_model(None)
        assert store.active_model.value is None


class TestRootStoreErrorHandling:
    """Tests for error management methods."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        reset_store()

    def test_clear_error_gpu_error(self):
        """Clearing gpu_error field works."""
        store = get_store()
        store.gpu_error.value = "Some error"
        store.clear_error("gpu_error")
        assert store.gpu_error.value is None

    def test_clear_error_models_error(self):
        """Clearing models_error field works."""
        store = get_store()
        store.models_error.value = "Some error"
        store.clear_error("models_error")
        assert store.models_error.value is None

    def test_clear_error_last_error(self):
        """Clearing last_error field works."""
        store = get_store()
        store.last_error.value = "Some error"
        store.clear_error("last_error")
        assert store.last_error.value is None

    def test_clear_error_invalid_field(self):
        """Clearing invalid error field is handled gracefully."""
        store = get_store()
        # Should not raise
        store.clear_error("invalid_field")

    def test_clear_all_errors(self):
        """Clearing all errors clears all error fields."""
        store = get_store()
        store.gpu_error.value = "GPU error"
        store.models_error.value = "Models error"
        store.last_error.value = "Last error"

        store.clear_all_errors()

        assert store.gpu_error.value is None
        assert store.models_error.value is None
        assert store.last_error.value is None


class TestRootStoreProperties:
    """Tests for store properties."""

    def setup_method(self):
        """Reset store before each test."""
        reset_store()

    def teardown_method(self):
        """Clean up after each test."""
        reset_store()

    def test_gpu_monitor_property_initial(self):
        """GPU monitor property returns None initially."""
        store = get_store()
        assert store.gpu_monitor is None

    def test_api_client_property_initial(self):
        """API client property returns None initially."""
        store = get_store()
        assert store.api_client is None
