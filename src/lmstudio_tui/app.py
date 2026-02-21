"""Main Textual application for LM Studio TUI."""

import asyncio

from textual.app import App
from textual.worker import get_current_worker

from lmstudio_tui.screens.main_screen import MainScreen
from lmstudio_tui.store import RootStore, get_store


class LMStudioApp(App):
    """LM Studio TUI Application."""

    CSS_PATH = None  # Will add later
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("?", "help", "Help"),
    ]

    def __init__(self, *args, **kwargs):
        """Initialize the application and store."""
        super().__init__(*args, **kwargs)
        self.store: RootStore = get_store()
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
        while True:
            try:
                worker = get_current_worker()
                if worker.is_cancelled:
                    break

                if self.store.gpu_monitor is None:
                    # GPU monitoring stopped, exit worker
                    break

                metrics = self.store.gpu_monitor.get_metrics()
                self.store.gpu_metrics.value = metrics
                self.store.gpu_error.value = None

            except Exception as e:
                self.store.gpu_error.value = str(e)
                self.store.last_error.value = f"GPU Monitor Error: {e}"

            # Sleep for configured update frequency
            await asyncio.sleep(self.store.config.value.gpu.update_frequency)

    async def _models_update_worker(self) -> None:
        """Update model list every 5.0 seconds.

        This worker fetches the list of available models from the LM Studio
        API and updates the store. It also maintains the server_connected
        state based on fetch success/failure.
        """
        while True:
            try:
                worker = get_current_worker()
                if worker.is_cancelled:
                    break

                # Ensure API client is connected
                if self.store.api_client is None and not self.store.connect_to_server():
                    # Connection failed, wait and retry
                    await asyncio.sleep(5.0)
                    continue

                # Fetch models from API
                models = await self.store.api_client.get_models()
                self.store.models.value = models
                self.store.models_error.value = None
                self.store.server_connected.value = True

                # Auto-update active_model if a model is loaded but none selected
                if self.store.active_model.value is None:
                    for model in models:
                        if model.loaded:
                            self.store.active_model.value = model.id
                            break

            except Exception as e:
                self.store.models_error.value = str(e)
                self.store.server_connected.value = False
                self.store.last_error.value = f"API Error: {e}"

            await asyncio.sleep(5.0)

    async def _connection_check_worker(self) -> None:
        """Check server connection periodically.

        This worker performs an initial connection check and then
        periodically verifies the connection is still alive.
        """
        # Initial connection attempt
        self.store.connect_to_server()

        # Continue checking connection every 30 seconds
        while True:
            try:
                worker = get_current_worker()
                if worker.is_cancelled:
                    break

                # Simple health check - if we have an API client, we're connected
                if self.store.api_client is not None:
                    self.store.server_connected.value = True
                else:
                    # Try to reconnect
                    self.store.connect_to_server()

            except Exception as e:
                self.store.server_connected.value = False
                self.store.last_error.value = f"Connection Check Error: {e}"

            await asyncio.sleep(30.0)

    def action_refresh(self) -> None:
        """Refresh all data."""
        # Trigger immediate updates by clearing error states
        self.store.clear_all_errors()
        self.notify("Refreshing data...")

        # The background workers will pick up fresh data on their next cycle
        # For immediate refresh, we could trigger the workers here

    def action_help(self) -> None:
        """Show help."""
        self.notify("Help: Press q to quit, r to refresh")

    async def on_shutdown(self) -> None:
        """App shutdown - cleanup resources."""
        self.store.stop_gpu_monitoring()
        self.store.disconnect_from_server()


def main():
    """Entry point for the application."""
    app = LMStudioApp()
    app.run()


if __name__ == "__main__":
    main()
