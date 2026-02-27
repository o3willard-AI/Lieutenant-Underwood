"""Main Textual application for LM Studio TUI."""

import asyncio
import logging
import sys

from textual.app import App
from textual.worker import get_current_worker

from lmstudio_tui.screens.main_screen import MainScreen
from lmstudio_tui.store import RootStore, get_store

# Configure logging - write to file only, suppress stdout/stderr to prevent TUI corruption
# Remove all existing handlers first to prevent duplicate or stderr output
root_logger = logging.getLogger()
root_logger.handlers = []  # Clear any existing handlers
root_logger.setLevel(logging.INFO)

# Create file handler only
file_handler = logging.FileHandler('/tmp/lmstudio-tui.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
root_logger.addHandler(file_handler)

# Ensure no propagation to default handlers
logging.getLogger().propagate = False

logger = logging.getLogger(__name__)


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

    def __init__(self, *args, **kwargs):
        """Initialize the application and store."""
        super().__init__(*args, **kwargs)
        self.store: RootStore = get_store()
        self._shutdown_event = asyncio.Event()
        # Load config from default location
        self.store.load_config()

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

        # Start models update worker
        self.run_worker(self._models_update_worker(), name="models_updater")

        # Initial connection check
        self.run_worker(self._connection_check_worker(), name="connection_checker")

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
                self.store.models_error.value = str(e)
                self.store.server_connected.value = False
                self.store.last_error.value = f"API Error: {e}"

            # Wait for shutdown signal or timeout
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                pass

    async def _connection_check_worker(self) -> None:
        """Check server connection periodically.

        This worker performs an initial connection check and then
        periodically verifies the connection is still alive.
        """
        # Initial connection attempt
        self.store.connect_to_server()

        # Continue checking connection every 30 seconds
        while not self._shutdown_event.is_set():
            try:
                # Simple health check - if we have an API client, we're connected
                if self.store.api_client is not None:
                    self.store.server_connected.value = True
                else:
                    # Try to reconnect
                    self.store.connect_to_server()

            except Exception as e:
                self.store.server_connected.value = False
                self.store.last_error.value = f"Connection Check Error: {e}"

            # Wait for shutdown signal or timeout
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=30.0
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
        await asyncio.sleep(0.1)  # Wait for workers to exit
        self.store.stop_gpu_monitoring()
        self.store.disconnect_from_server()


def main():
    """Entry point for the application."""
    app = LMStudioApp()
    app.run()


if __name__ == "__main__":
    main()
