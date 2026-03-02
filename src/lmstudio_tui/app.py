"""Main Textual application for LM Studio TUI."""

import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

from textual.app import App
from textual.worker import get_current_worker

from lmstudio_tui.screens.main_screen import MainScreen
from lmstudio_tui.store import RootStore, get_store

def _setup_logging() -> logging.Logger:
    """Configure secure file-based logging with rotation.
    
    Uses ~/.local/share/lmstudio-tui/ for log storage with
    RotatingFileHandler for automatic log rotation.
    """
    # Create secure log directory
    log_dir = Path.home() / ".local" / "share" / "lmstudio-tui"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers = []  # Clear existing handlers
    root_logger.setLevel(logging.INFO)
    
    # Create rotating file handler (5MB max, 3 backups)
    log_file = log_dir / "app.log"
    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    root_logger.addHandler(handler)
    
    # Prevent propagation to avoid duplicate logs
    logging.getLogger().propagate = False
    
    return logging.getLogger(__name__)

logger = _setup_logging()


class LMStudioApp(App):
    """LM Studio TUI Application."""

    CSS_PATH = None  # Will add later
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("?", "help", "Help"),
        ("tab", "focus_next", "Next Panel"),
        ("l", "load_model", "Load Model"),
        ("u", "unload_model", "Unload Model"),
    ]

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, *args, **kwargs):
        """Initialize the application and store.

        Args:
            host: Override the server host from config (used by launcher).
            port: Override the server port from config (used by launcher).
        """
        super().__init__(*args, **kwargs)
        self.store: RootStore = get_store()
        self._shutdown_event = asyncio.Event()
        # Exponential backoff state for models worker
        self._models_backoff_delay = 5.0
        self._models_max_backoff = 60.0
        # Load config from default location
        self.store.load_config()
        # Apply CLI / launcher overrides after config load
        if host is not None:
            self.store.config.value.server.host = host
        if port is not None:
            self.store.config.value.server.port = port

    def on_mount(self) -> None:
        """App startup - initialize store and start background workers."""
        self.push_screen(MainScreen())

        # Start GPU monitoring worker if GPU available
        if self.store.start_gpu_monitoring():
            self.run_worker(self._gpu_update_worker(), name="gpu_updater")
        else:
            self.notify(
                "GPU monitoring not available - no NVIDIA GPUs detected",
                severity="warning",
            )

        # Start models update worker (also handles connection health)
        self.run_worker(self._models_update_worker(), name="models_updater")

    async def _gpu_update_worker(self) -> None:
        """Update GPU metrics every config.gpu.update_frequency seconds.

        This worker runs continuously in the background, fetching fresh
        GPU metrics and updating the store. Exceptions are caught and
        stored in the error fields without crashing the worker.
        """
        while not self._shutdown_event.is_set():
            try:
                monitor = self.store.gpu_monitor
                if monitor is None:
                    # GPU monitoring stopped, exit worker
                    break

                metrics = monitor.get_metrics()
                self.store.gpu_metrics.value = metrics
                self.store.gpu_error.value = None

            except Exception as e:
                self.store.gpu_error.value = str(e)
                self.store.last_error.value = f"GPU Monitor Error: {e}"

            # Wait for shutdown signal or timeout
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.store.config.value.gpu.update_frequency
                )
            except asyncio.TimeoutError:
                pass

    async def _models_update_worker(self) -> None:
        """Update model list every 5.0 seconds.

        This worker fetches the list of available models from the LM Studio
        API and updates the store. It also maintains the server_connected
        state based on fetch success/failure.
        """
        logger.info("=== Models update worker started ===")
        while not self._shutdown_event.is_set():
            try:
                # Ensure API client is connected
                if self.store.api_client is None and not self.store.connect_to_server():
                    logger.warning("API client not connected, waiting...")
                    await asyncio.sleep(5.0)
                    continue

                # Fetch models from API
                logger.info("Fetching models from API...")
                models = await self.store.api_client.get_models()
                logger.info(f"Fetched {len(models)} models")
                for i, m in enumerate(models):
                    logger.info(f"  Model {i}: id={m.id}, name={m.name}, loaded={m.loaded}, size={m.size}")
                
                self.store.models.value = models
                self.store.models_error.value = None
                self.store.server_connected.value = True

                # Auto-update active_model if a model is loaded but none selected
                if self.store.active_model.value is None:
                    for model in models:
                        if model.loaded:
                            self.store.active_model.value = model.id
                            logger.info(f"Auto-set active model: {model.id}")
                            break

            except Exception as e:
                logger.error(f"Models worker error: {e}", exc_info=True)
                cfg = self.store.config.value.server
                user_msg = (
                    f"Cannot reach LM Studio at {cfg.host}:{cfg.port} — "
                    f"retrying in {int(self._models_backoff_delay)}s"
                )
                self.store.models_error.value = user_msg
                self.store.server_connected.value = False
                self.store.last_error.value = f"API Error: {e}"
                # Exponential backoff on error
                self._models_backoff_delay = min(
                    self._models_backoff_delay * 2,
                    self._models_max_backoff
                )
                logger.info(f"Backing off for {self._models_backoff_delay}s before retry")
            else:
                # Reset backoff on success
                if self._models_backoff_delay != 5.0:
                    self._models_backoff_delay = 5.0
                    logger.info("Reset backoff to 5s after successful fetch")

            # Wait for shutdown signal or timeout (uses backoff delay)
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._models_backoff_delay
                )
            except asyncio.TimeoutError:
                pass

    def action_refresh(self) -> None:
        """Refresh all data."""
        # Trigger immediate updates by clearing error states
        self.store.clear_all_errors()
        self.notify("Refreshing data...")

        # The background workers will pick up fresh data on their next cycle
        # For immediate refresh, we could trigger the workers here

    def action_help(self) -> None:
        """Show help."""
        self.notify(
            "Help: q=quit, r=refresh, l=load, u=unload, Enter=details, Tab=next panel, ?=help"
        )

    def action_focus_next(self) -> None:
        """Move focus to the next panel."""
        self.screen.focus_next()

    def action_load_model(self) -> None:
        """Load the currently selected model."""
        logger.info("=== APP action_load_model called ===")
        from lmstudio_tui.widgets.models_panel import ModelsPanel
        try:
            models_panel = self.screen.query_one(ModelsPanel)
            logger.info(f"Found models_panel: {models_panel}")
            self.run_worker(models_panel.action_load_model())
            logger.info("Worker scheduled for load action")
        except Exception as e:
            logger.error(f"Error in action_load_model: {e}", exc_info=True)
            self.notify(f"Error loading model: {e}", severity="error")

    def action_unload_model(self) -> None:
        """Unload the currently selected model."""
        # Find the models panel and trigger unload action
        from lmstudio_tui.widgets.models_panel import ModelsPanel
        try:
            models_panel = self.screen.query_one(ModelsPanel)
            self.run_worker(models_panel.action_unload_model())
        except Exception as e:
            self.notify(f"Error unloading model: {e}", severity="error")

    async def on_shutdown(self) -> None:
        """App shutdown - signal all workers to exit gracefully."""
        self._shutdown_event.set()
        await asyncio.sleep(0.1)  # Give workers a chance to observe the event
        self.store.stop_gpu_monitoring()
        await self.store.disconnect_from_server()


def main():
    """Entry point for the application."""
    app = LMStudioApp()
    app.run()


if __name__ == "__main__":
    main()
