"""Central reactive state store for LM Studio TUI.

This module implements the RootStore singleton pattern for managing
application state. It provides a custom reactive implementation that
allows UI components to watch for state changes.

Answers to Open Questions from Design Doc:

1. Config Path Resolution: The store auto-discovers config at ~/.config/lmstudio-tui/config.toml
   but also accepts explicit paths via load_config(path). This provides sensible defaults while
   allowing override for testing and custom deployments.

2. Active Model Detection: active_model is explicitly set by user action (set_active_model).
   The app.py background worker auto-detects loaded models and sets this, but user can override.

3. Worker Restart on Config Change: Currently the GPU worker does NOT detect config changes
   at runtime. To change intervals, the worker would need to be restarted (future enhancement).

4. API Client Lifecycle: The API client is created once in connect_to_server() and reused.
   This gives connection pooling benefits and simpler lifecycle management.

5. Store Package vs Module: A single module (store.py) is sufficient for current project size.
    If we add more state-related modules later, we can refactor to store/__init__.py.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Generic, Optional, TypeVar

from lmstudio_tui.api.client import LMStudioClient, ModelInfo
from lmstudio_tui.config import AppConfig
from lmstudio_tui.gpu.monitor import GPUMetrics, GPUMonitor

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ReactiveVar(Generic[T]):
    """A reactive variable that notifies watchers on change.

    This is a simplified reactive implementation that works without
    Textual's DOM infrastructure. UI components can register callbacks
    that will be invoked when the value changes.

    Example:
        var = ReactiveVar(0)
        var.watch(lambda old, new: print(f"Changed from {old} to {new}"))
        var.value = 5  # Prints: Changed from 0 to 5
    """

    def __init__(self, default: T) -> None:
        """Initialize with a default value.

        Args:
            default: The initial value of this reactive variable.
        """
        self._value: T = default
        self._watchers: list[Callable[[T, T], None]] = []
        self._lock = threading.Lock()

    @property
    def value(self) -> T:
        """Get the current value."""
        return self._value

    @value.setter
    def value(self, new_value: T) -> None:
        """Set a new value and notify watchers.

        Args:
            new_value: The new value to set.
        """
        with self._lock:
            old_value = self._value
            self._value = new_value

            # Copy watchers list to avoid issues if modified during iteration
            watchers = self._watchers.copy()

        # Notify watchers outside the lock
        if old_value != new_value:
            for watcher in watchers:
                try:
                    watcher(old_value, new_value)
                except Exception as e:
                    logger.error(f"Error in reactive watcher: {e}")

    def watch(self, callback: Callable[[T, T], None]) -> Callable[[], None]:
        """Register a callback to be called when the value changes.

        Args:
            callback: Function(old_value, new_value) called on change.

        Returns:
            A function that can be called to unregister the watcher.
        """
        with self._lock:
            self._watchers.append(callback)

        def unwatch() -> None:
            with self._lock:
                if callback in self._watchers:
                    self._watchers.remove(callback)

        return unwatch

    def __repr__(self) -> str:
        return f"ReactiveVar({self._value!r})"


@dataclass
class ModelLoadConfig:
    """Per-model load configuration stored as defaults.

    These settings are persisted per-model and used when loading.
    Changes require unload+reload to take effect.
    """
    gpu_offload_percent: int = 100  # 0-100 or -1 for "Max"
    context_length: int = 8192  # Selected from predefined options
    kv_cache_quantization: str = "f16"  # f16, q8_0, q4_0, etc.


@dataclass
class StoreState:
    """Container for all reactive state fields.

    This dataclass holds all the reactive variables for the store,
    making initialization and reset cleaner.
    """
    config: ReactiveVar[AppConfig] = field(default_factory=lambda: ReactiveVar(AppConfig()))
    gpu_metrics: ReactiveVar[list[GPUMetrics]] = field(default_factory=lambda: ReactiveVar([]))
    gpu_error: ReactiveVar[Optional[str]] = field(default_factory=lambda: ReactiveVar(None))
    models: ReactiveVar[list[ModelInfo]] = field(default_factory=lambda: ReactiveVar([]))
    active_model: ReactiveVar[Optional[str]] = field(default_factory=lambda: ReactiveVar(None))
    models_error: ReactiveVar[Optional[str]] = field(default_factory=lambda: ReactiveVar(None))
    server_connected: ReactiveVar[bool] = field(default_factory=lambda: ReactiveVar(False))
    last_error: ReactiveVar[Optional[str]] = field(default_factory=lambda: ReactiveVar(None))
    # Model loading state for UI feedback
    model_loading: ReactiveVar[Optional[str]] = field(default_factory=lambda: ReactiveVar(None))
    model_loading_dots: ReactiveVar[int] = field(default_factory=lambda: ReactiveVar(0))
    # Per-model load configurations (model_id -> config)
    model_configs: ReactiveVar[dict[str, ModelLoadConfig]] = field(default_factory=lambda: ReactiveVar({}))


class RootStore:
    """Central reactive state store for LM Studio TUI.

    This singleton class holds all application state with reactive fields
    that notify watchers when changed. UI components can watch state
    changes and update accordingly.

    The store is thread-safe and uses double-checked locking for singleton
    initialization.

    Example:
        store = get_store()
        store.gpu_metrics.value = [...]  # UI watchers notified

        # In a widget:
        store.gpu_metrics.watch(self._update_gpu_display)
    """

    # Singleton pattern with thread-safe double-checked locking
    _instance: Optional[RootStore] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> RootStore:
        """Create or return the singleton instance.

        Uses double-checked locking for thread-safe singleton initialization.

        Returns:
            The singleton RootStore instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # Initialize immediately in __new__ to avoid __init__ issues
                    cls._instance._state = StoreState()
                    cls._instance._gpu_monitor: Optional[GPUMonitor] = None
                    cls._instance._api_client: Optional[LMStudioClient] = None
                    cls._instance._config_path: Optional[Path] = None
        return cls._instance

    def __init__(self) -> None:
        """Initialize the store instance.

        This is called every time RootStore() is invoked, but the singleton
        ensures only one instance exists. Actual initialization happens
        in __new__ to avoid double-initialization issues.
        """
        # Initialization is done in __new__ to ensure it only happens once
        pass

    # Property accessors for reactive state

    @property
    def config(self) -> ReactiveVar[AppConfig]:
        """Application configuration."""
        return self._state.config

    @property
    def gpu_metrics(self) -> ReactiveVar[list[GPUMetrics]]:
        """Current GPU metrics."""
        return self._state.gpu_metrics

    @property
    def gpu_error(self) -> ReactiveVar[Optional[str]]:
        """GPU monitoring error (if any)."""
        return self._state.gpu_error

    @property
    def models(self) -> ReactiveVar[list[ModelInfo]]:
        """Available models from LM Studio API."""
        return self._state.models

    @property
    def active_model(self) -> ReactiveVar[Optional[str]]:
        """Currently active/selected model ID."""
        return self._state.active_model

    @property
    def models_error(self) -> ReactiveVar[Optional[str]]:
        """Model fetching error (if any)."""
        return self._state.models_error

    @property
    def server_connected(self) -> ReactiveVar[bool]:
        """Connection status to LM Studio server."""
        return self._state.server_connected

    @property
    def last_error(self) -> ReactiveVar[Optional[str]]:
        """Most recent global error message."""
        return self._state.last_error

    @property
    def model_loading(self) -> ReactiveVar[Optional[str]]:
        """ID of model currently being loaded (None if not loading)."""
        return self._state.model_loading

    @property
    def model_loading_dots(self) -> ReactiveVar[int]:
        """Animation counter for loading dots."""
        return self._state.model_loading_dots

    @property
    def model_configs(self) -> ReactiveVar[dict[str, ModelLoadConfig]]:
        """Per-model load configurations."""
        return self._state.model_configs

    # Configuration Methods

    def load_config(self, path: Optional[Path] = None) -> None:
        """Load configuration from TOML file.

        If no path is provided, uses default location (~/.config/lmstudio-tui/config.toml)
        which returns defaults if the file doesn't exist.

        Args:
            path: Path to TOML config file. If None, uses default location.

        Example:
            store.load_config()  # Loads from default location
            store.load_config(Path("/custom/config.toml"))  # Loads custom file
        """
        if path is not None:
            self._config_path = path
            self.config.value = AppConfig.load(path)
        else:
            # Try default locations
            default_path = Path.home() / ".config" / "lmstudio-tui" / "config.toml"
            self._config_path = default_path
            self.config.value = AppConfig.load(default_path)

        logger.info(f"Configuration loaded from {self._config_path}")

    def save_config(self, path: Optional[Path] = None) -> None:
        """Save current configuration to TOML file.

        Args:
            path: Path to save config file. If None, uses previously loaded path
                  or defaults to ~/.config/lmstudio-tui/config.toml

        Example:
            store.save_config()  # Saves to previously loaded/default path
            store.save_config(Path("/backup/config.toml"))  # Saves to custom path
        """
        save_path = path or self._config_path or Path.home() / ".config" / "lmstudio-tui" / "config.toml"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.value.save(save_path)
        logger.info(f"Configuration saved to {save_path}")

    # GPU Operations

    def start_gpu_monitoring(self) -> bool:
        """Initialize GPU monitoring.

        Attempts to start the GPU monitor using NVML. If no NVIDIA GPUs
        are available or NVML fails to initialize, returns False.

        Returns:
            True if GPU monitoring started successfully, False otherwise.

        Example:
            if store.start_gpu_monitoring():
                print("GPU monitoring enabled")
            else:
                print("No NVIDIA GPUs detected")
        """
        if self._gpu_monitor is not None:
            logger.debug("GPU monitor already started")
            return True

        self._gpu_monitor = GPUMonitor()
        started = self._gpu_monitor.start()

        if started:
            logger.info("GPU monitoring started successfully")
            gpu_count = self._gpu_monitor._gpu_count
            logger.info(f"Detected {gpu_count} NVIDIA GPU(s)")
        else:
            logger.warning("GPU monitoring not available - no NVIDIA GPUs detected")
            self._gpu_monitor = None

        return started

    def stop_gpu_monitoring(self) -> None:
        """Stop GPU monitoring and cleanup resources.

        Safe to call even if monitoring was never started or failed.
        """
        if self._gpu_monitor is not None:
            self._gpu_monitor.shutdown()
            self._gpu_monitor = None
            self.gpu_metrics.value = []
            self.gpu_error.value = None
            logger.info("GPU monitoring stopped")

    @property
    def gpu_monitor(self) -> Optional[GPUMonitor]:
        """Get the GPU monitor instance (if started).

        Returns:
            GPUMonitor instance if started, None otherwise.
        """
        return self._gpu_monitor

    # API Operations

    def connect_to_server(self) -> bool:
        """Connect to LM Studio server.

        Creates an LMStudioClient using the current server configuration.
        The client is persisted for connection pooling benefits.

        Returns:
            True if connection client created successfully, False otherwise.

        Example:
            if store.connect_to_server():
                print("Connected to LM Studio")
            else:
                print("Connection failed")
        """
        if self._api_client is not None:
            logger.debug("API client already connected")
            return True

        try:
            self._api_client = LMStudioClient.from_config(self.config.value.server)
            logger.info(f"LM Studio client created for {self.config.value.server.host}:{self.config.value.server.port}")
            self.server_connected.value = True
            return True
        except Exception as e:
            logger.error(f"Failed to connect to LM Studio: {e}")
            self.server_connected.value = False
            self.last_error.value = f"Connection Error: {e}"
            return False

    async def disconnect_from_server(self) -> None:
        """Disconnect from LM Studio server and cleanup resources.

        Safe to call even if not connected.
        """
        if self._api_client is not None:
            try:
                await self._api_client.close()
            except Exception as e:
                logger.warning(f"Error during client disconnect: {e}")
            finally:
                self._api_client = None
                self.server_connected.value = False
                logger.info("Disconnected from LM Studio server")

    @property
    def api_client(self) -> Optional[LMStudioClient]:
        """Get the API client instance (if connected).

        Returns:
            LMStudioClient instance if connected, None otherwise.
        """
        return self._api_client

    # State Actions

    def set_active_model(self, model_id: Optional[str]) -> None:
        """Set the currently active/selected model.

        Args:
            model_id: The ID of the model to activate, or None to clear.

        Example:
            store.set_active_model("llama-2-7b")
            store.set_active_model(None)  # Clear active model
        """
        self.active_model.value = model_id
        if model_id:
            logger.info(f"Active model set to: {model_id}")
        else:
            logger.info("Active model cleared")

    def clear_error(self, error_field: str) -> None:
        """Clear a specific error field.

        Args:
            error_field: Name of the error field to clear
                        (gpu_error, models_error, last_error).

        Example:
            store.clear_error("gpu_error")
            store.clear_error("last_error")
        """
        valid_fields = {"gpu_error", "models_error", "last_error"}
        if error_field in valid_fields:
            getattr(self, error_field).value = None
            logger.debug(f"Cleared error field: {error_field}")
        else:
            logger.warning(f"Invalid error field: {error_field}")

    def clear_all_errors(self) -> None:
        """Clear all error fields at once.

        Convenience method to reset error state, typically called
        when refreshing data or starting a new operation.
        """
        self.gpu_error.value = None
        self.models_error.value = None
        self.last_error.value = None
        logger.debug("All error fields cleared")

    def get_model_config(self, model_id: str) -> ModelLoadConfig:
        """Get load configuration for a model.

        Returns existing config or creates default if not set.

        Args:
            model_id: The model identifier.

        Returns:
            ModelLoadConfig for the model.
        """
        configs = self.model_configs.value
        if model_id not in configs:
            configs[model_id] = ModelLoadConfig()
            self.model_configs.value = configs  # Trigger reactive update
        return configs[model_id]

    def set_model_config(self, model_id: str, config: ModelLoadConfig) -> None:
        """Set load configuration for a model.

        Args:
            model_id: The model identifier.
            config: The load configuration to store.
        """
        configs = self.model_configs.value
        configs[model_id] = config
        self.model_configs.value = configs  # Trigger reactive update
        logger.info(f"Updated load config for model: {model_id}")

    def calculate_max_context(self, model_id: str, vram_available_mb: int) -> int:
        """Calculate maximum context length that fits in available VRAM.

        Args:
            model_id: The model identifier.
            vram_available_mb: Available VRAM in MB.

        Returns:
            Maximum context length that fits.
        """
        # Find the model info
        model_info = None
        for m in self.models.value:
            if m.id == model_id:
                model_info = m
                break

        if not model_info:
            return 8192  # Default fallback

        max_supported = model_info.max_context_length
        if max_supported <= 0:
            max_supported = 262144  # Assume large if unknown

        # Rough calculation: KV cache uses ~4 bytes per token per parameter
        # For a typical 7B model: ~28MB per 1k context
        # For a 30B model: ~120MB per 1k context
        # This is a simplified estimate
        model_size_gb = model_info.size / (1024**3) if model_info.size > 0 else 7.0
        mb_per_1k_context = model_size_gb * 4  # Rough estimate

        if mb_per_1k_context <= 0:
            return 8192

        max_context_1k = int(vram_available_mb / mb_per_1k_context)
        max_context = max_context_1k * 1024

        # Cap at model's max supported
        return min(max_context, max_supported)


def get_store() -> RootStore:
    """Get the singleton RootStore instance.

    This is the preferred way to access the store from anywhere in the app.

    Returns:
        The singleton RootStore instance.

    Example:
        from lmstudio_tui.store import get_store

        store = get_store()
        store.set_active_model("my-model")
    """
    return RootStore()


def reset_store() -> None:
    """Reset the singleton instance (for testing only).

    This function clears the singleton instance so that a fresh
    RootStore will be created on the next get_store() call.

    WARNING: This is intended for testing purposes only. Do not
    call this in production code as it can cause state loss.
    """
    with RootStore._lock:
        RootStore._instance = None
