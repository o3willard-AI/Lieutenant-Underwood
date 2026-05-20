"""Main Textual application for LM Studio TUI."""

import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

from textual.app import App
from textual.theme import ThemeProvider
from textual.worker import get_current_worker

from lmstudio_tui.network.http_sniffer import HTTPSniffer
from lmstudio_tui.screens.main_screen import MainScreen
from lmstudio_tui.store import RootStore, get_store

_DEFAULT_THEME = "textual-dark"


class _MarkedThemeProvider(ThemeProvider):
    """Theme picker that marks the currently active theme and the built-in default.

    Overrides the bare name list from Textual's ThemeProvider so users can
    see which theme is active and which is the original default before making
    a selection.  A toast notification confirms every change.
    """

    @property
    def commands(self) -> list[tuple[str, object]]:
        current = self.app.theme
        result = []
        for theme in self.app.available_themes.values():
            if theme.name == "textual-ansi":
                continue
            tags = []
            if theme.name == current:
                tags.append("current")
            if theme.name == _DEFAULT_THEME:
                tags.append("default")
            label = f"{theme.name} ({', '.join(tags)})" if tags else theme.name

            def _apply(name: str = theme.name) -> None:
                self.app.theme = name
                self.app.notify(f"Theme: {name}", timeout=2)

            result.append((label, _apply))
        return result

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
        ("?", "help", "Help"),
        ("tab", "focus_next", "Next Panel"),
        ("d", "browse_models", "Browse Models"),
    ]

    def search_themes(self) -> None:
        """Override Textual's theme search to mark the current and default themes."""
        from textual.command import CommandPalette
        self.push_screen(
            CommandPalette(
                providers=[_MarkedThemeProvider],
                placeholder="Search themes… (current/default marked)",
            )
        )

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

        # Initialize lms CLI (hybrid load path)
        if self.store.initialize_lms_cli():
            logger.info("lms CLI found — using hybrid load path")
        else:
            logger.warning("lms CLI not found — using REST API fallback for model loading")

        # Start GPU monitoring worker if GPU available
        if self.store.start_gpu_monitoring():
            self.run_worker(self._gpu_update_worker(), name="gpu_updater")
        else:
            self.notify(
                "GPU monitoring not available - no NVIDIA GPUs detected",
                severity="warning",
            )

        # Start CPU monitoring worker
        if self.store.start_cpu_monitoring():
            self.run_worker(self._cpu_update_worker(), name="cpu_updater")
        else:
            logger.warning("CPU monitoring not available")

        # Start models update worker (also handles connection health)
        self.run_worker(self._models_update_worker(), name="models_updater")

        # Start download monitor (polls detached lms-get processes)
        self.run_worker(self._download_monitor_worker(), name="download_monitor")

        # Start passive HTTP sniffer for external inference traffic
        port = self.store.config.value.server.port
        self._http_sniffer = HTTPSniffer(self.store)
        if not self._http_sniffer.start(port):
            if not self._http_sniffer.available:
                logger.warning(
                    "Network sniffer unavailable — re-run installer to fix: "
                    "sudo bash install.sh --upgrade"
                )
        self.run_worker(self._port_watch_worker(), name="port_watcher")

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
                if metrics:
                    avg_util = sum(g.utilization for g in metrics) / len(metrics)
                    self.store.record_gpu_utilization(avg_util)

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

    async def _cpu_update_worker(self) -> None:
        """Update CPU and RAM metrics every config.gpu.update_frequency seconds."""
        while not self._shutdown_event.is_set():
            try:
                monitor = self.store.cpu_monitor
                if monitor is None:
                    break
                metrics = monitor.get_metrics()
                self.store.cpu_metrics.value = metrics
                self.store.cpu_error.value = None
            except Exception as e:
                self.store.cpu_error.value = str(e)

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.store.config.value.gpu.update_frequency,
                )
            except asyncio.TimeoutError:
                pass

    async def _download_monitor_worker(self) -> None:
        """Watch store.download_progress for download completion and notify.

        The download itself runs as an app-level worker (stream_download in
        downloader.py) and pushes progress directly to the store.  This worker
        only needs to detect the running→done transition and fire a notification
        plus model-list refresh once per download.
        """
        last_was_running = False

        while not self._shutdown_event.is_set():
            try:
                prog = self.store.download_progress.value
                is_running = prog is not None and prog.is_running

                if last_was_running and not is_running and prog is not None:
                    # Download just completed (success or error)
                    if prog.error and prog.error != "Cancelled":
                        self.notify(
                            f"Download failed: {prog.error}",
                            severity="error",
                        )
                    elif not prog.error:
                        self.notify(
                            f"✓ Downloaded: {prog.filename}",
                            severity="information",
                        )
                        # Refresh model list so LM Studio-indexed models appear
                        try:
                            client = self.store.api_client
                            if client:
                                models = await client.get_models()
                                self.store.models.value = models
                        except Exception:
                            pass

                last_was_running = is_running

            except Exception as e:
                logger.error(f"Download monitor error: {e}")

            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _port_watch_worker(self) -> None:
        """Restart the HTTP sniffer whenever the configured server port changes.

        Polls every 5 s.  The launcher auto-detects the port at startup and
        writes it into store.config; if the user edits config while the TUI
        is running the sniffer will follow within one poll cycle.
        """
        while not self._shutdown_event.is_set():
            sniffer = getattr(self, "_http_sniffer", None)
            if sniffer and sniffer.available:
                current_port = self.store.config.value.server.port
                if current_port and current_port != sniffer.port:
                    sniffer.update_port(current_port)
                    self.notify(
                        f"Network sniffer moved to port {current_port}",
                        severity="information",
                        timeout=3,
                    )
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    def action_help(self) -> None:
        """Show help."""
        self.notify(
            "Help: q=quit, Enter=model config/load/unload, Tab=next panel, d=browse, ?=help"
        )

    def action_focus_next(self) -> None:
        """Move focus to the next panel."""
        self.screen.focus_next()

    def action_browse_models(self) -> None:
        """Open the model browser screen."""
        from lmstudio_tui.screens.model_browser_screen import ModelBrowserScreen
        self.push_screen(ModelBrowserScreen())

    async def on_shutdown(self) -> None:
        """App shutdown - signal all workers to exit gracefully."""
        self._shutdown_event.set()
        await asyncio.sleep(0.1)  # Give workers a chance to observe the event
        self.store.stop_gpu_monitoring()
        self.store.stop_cpu_monitoring()
        await self.store.disconnect_from_server()
        if hasattr(self, "_http_sniffer"):
            self._http_sniffer.stop()


def main():
    """Entry point for the application."""
    app = LMStudioApp()
    app.run()


if __name__ == "__main__":
    main()
