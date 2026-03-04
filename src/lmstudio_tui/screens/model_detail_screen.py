"""Model detail screen for LM Studio TUI.

Displays detailed information about a model with Load/Unload controls.
This is a modal screen that appears when the user selects a model
and presses Enter.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from lmstudio_tui.api.client import ModelInfo
from lmstudio_tui.store import get_store
from lmstudio_tui.utils import extract_quantization

logger = logging.getLogger(__name__)


class ModelDetailScreen(ModalScreen[Optional[str]]):
    """Modal screen showing model details with Load/Unload controls.

    Returns:
        Action taken: "loaded", "unloaded", or None if cancelled.
    """

    DEFAULT_CSS = """
    ModelDetailScreen {
        align: center middle;
        background: $background 80%;
    }
    ModelDetailScreen > Container {
        width: 80;
        height: auto;
        max-height: 22;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    ModelDetailScreen Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        content-align: center middle;
        margin-bottom: 1;
    }
    ModelDetailScreen Static.label {
        color: $text-muted;
        width: 12;
    }
    ModelDetailScreen Static.value {
        color: $text;
        width: 1fr;
    }
    ModelDetailScreen Static.status-loaded {
        color: $success;
        text-style: bold;
    }
    ModelDetailScreen Static.status-standby {
        color: $text-muted;
    }
    ModelDetailScreen Static.error {
        color: $error;
        text-style: bold;
        content-align: center middle;
        margin-top: 1;
    }
    ModelDetailScreen Static.loading {
        color: $primary;
        text-style: bold;
        content-align: center middle;
        height: 1;
        margin-top: 1;
    }
    ModelDetailScreen Horizontal.info-row {
        height: 1;
        margin-bottom: 1;
    }
    ModelDetailScreen Horizontal.buttons {
        height: auto;
        margin-top: 1;
        content-align: center middle;
    }
    ModelDetailScreen Button {
        margin: 0 1;
    }
    """

    def __init__(self, model_id: str, **kwargs):
        """Initialize the model detail screen."""
        super().__init__(**kwargs)
        self.model_id = model_id
        self._store = get_store()
        self._model: Optional[ModelInfo] = None
        self._ignore_enter = True
        self._loading = False
        self._loading_dots = 0
        self._loading_task = None   # Textual interval Timer
        self._loading_widget: Optional[Static] = None   # pre-composed; set in on_mount
        self._error_widget: Optional[Static] = None     # pre-composed; set in on_mount

    # ------------------------------------------------------------------
    # Compose / mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        with Container():
            yield Static("🤖 Model Details", classes="title")

            self._model = self._get_model()

            if self._model:
                with Horizontal(classes="info-row"):
                    yield Static("Name:", classes="label")
                    yield Static(self._model.name or self._model.id, classes="value")

                if self._model.name and self._model.name != self._model.id:
                    with Horizontal(classes="info-row"):
                        yield Static("ID:", classes="label")
                        yield Static(self._model.id, classes="value")

                quant = (
                    self._model.quantization
                    if self._model.quantization != "-"
                    else extract_quantization(self._model.id)
                )
                with Horizontal(classes="info-row"):
                    yield Static("Quant:", classes="label")
                    yield Static(quant, classes="value")

                if self._model.loaded and self._model.loaded_context_length > 0:
                    context_text = f"{self._model.loaded_context_length:,} / {self._model.max_context_length:,}"
                elif self._model.max_context_length > 0:
                    context_text = f"{self._model.max_context_length:,}"
                else:
                    context_text = "-"
                with Horizontal(classes="info-row"):
                    yield Static("Context:", classes="label")
                    yield Static(context_text, classes="value")

                status_text = "● Loaded" if self._model.loaded else "○ Standby"
                status_class = "status-loaded" if self._model.loaded else "status-standby"
                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="label")
                    yield Static(status_text, classes=f"value {status_class}")

                # Loading indicator and error — hidden until needed
                yield Static("", classes="loading", id="loading-indicator")
                yield Static("", classes="error", id="error-indicator")

                with Horizontal(classes="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    if self._model.loaded:
                        yield Button("Eject", id="unload-btn", variant="error")
                    else:
                        yield Button("Load", id="load-btn", variant="success")
            else:
                yield Static(f"Model '{self.model_id}' not found", classes="error")
                with Horizontal(classes="buttons"):
                    yield Button("Close", id="cancel-btn")

    def on_mount(self) -> None:
        """Wire up pre-composed dynamic widgets and protect against Enter auto-fire."""
        try:
            self._loading_widget = self.query_one("#loading-indicator", Static)
            self._loading_widget.display = False
        except Exception:
            self._loading_widget = None

        try:
            self._error_widget = self.query_one("#error-indicator", Static)
            self._error_widget.display = False
        except Exception:
            self._error_widget = None

        # Disable buttons for one render cycle so the Enter key that opened
        # this modal does not immediately fire Cancel.
        self._ignore_enter = True
        for btn in self.query(Button):
            btn.disabled = True
        self.call_after_refresh(self._enable_buttons_after_mount)

    def _enable_buttons_after_mount(self) -> None:
        """Re-enable buttons after the first render cycle and restore keyboard focus."""
        if not self._loading:
            for btn in self.query(Button):
                btn.disabled = False
        # Explicitly focus Cancel so arrow keys / Tab / Space / Enter all work.
        # Disabling widgets on mount causes Textual to drop focus; we must restore it.
        try:
            self.query_one("#cancel-btn", Button).focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses — load/unload run in a worker to avoid blocking the UI."""
        button_id = event.button.id

        if button_id == "load-btn":
            # run_worker prevents the event loop from blocking during the HTTP call.
            # If the user dismisses the modal while loading, Textual cancels the worker.
            self.run_worker(self._load_model(), exclusive=True)
        elif button_id == "unload-btn":
            self.run_worker(self._unload_model(), exclusive=True)
        elif button_id == "cancel-btn":
            self.dismiss(None)

    def key_escape(self) -> None:
        """Handle Escape key - close modal."""
        self.dismiss(None)

    def key_enter(self) -> None:
        """Ignore first Enter press (came from the parent screen that opened us)."""
        if self._ignore_enter:
            self._ignore_enter = False
            return


    # ------------------------------------------------------------------
    # Load / unload workers
    # ------------------------------------------------------------------

    async def _load_model(self) -> None:
        """Load model — runs in a Textual worker (non-blocking)."""
        if not self._model or self._model.loaded or self._loading:
            return

        self._start_loading()
        try:
            client = self._store.api_client
            if not client:
                self._show_error("Not connected to server")
                return

            # Resolve context length from the models-panel configuration frame
            config = self._store.get_model_config(self.model_id)
            if config.context_length == -1:  # Auto (Max VRAM)
                total_vram = sum(g.vram_total for g in self._store.gpu_metrics.value)
                used_vram = sum(g.vram_used for g in self._store.gpu_metrics.value)
                available_vram = max(0, total_vram - used_vram)
                context_length = self._store.calculate_max_context(self.model_id, available_vram)
            elif config.context_length == -2:  # Auto (Model Max)
                context_length = (
                    self._model.max_context_length
                    if self._model and self._model.max_context_length > 0
                    else 8192
                )
            else:
                context_length = config.context_length

            await client.load_model(self.model_id, context_length=context_length)

            # Dismiss immediately — load succeeded.
            # Refresh model list as best-effort; a timeout here must not
            # be reported as a load failure.
            self._stop_loading()
            self.dismiss("loaded")
            self.app.notify(f"Model '{self.model_id}' loaded successfully")
            try:
                models = await client.get_models()
                self._store.models.value = models
            except Exception:
                pass

        except asyncio.CancelledError:
            # User dismissed the modal while loading — that's fine.
            logger.info(f"Load of {self.model_id} cancelled")
        except Exception as e:
            logger.error(f"Failed to load model {self.model_id}: {e}")
            self._show_error(f"Failed to load: {e}")
            self._stop_loading()

    async def _unload_model(self) -> None:
        """Unload model — runs in a Textual worker (non-blocking)."""
        if not self._model or not self._model.loaded or self._loading:
            return

        if not self._model.instance_id:
            self._show_error("No instance ID available")
            return

        self._start_loading()
        try:
            client = self._store.api_client
            if not client:
                self._show_error("Not connected to server")
                return

            await client.unload_model(self._model.instance_id)

            if self._store.active_model.value == self.model_id:
                self._store.active_model.value = None

            # Dismiss immediately — unload succeeded.
            self._stop_loading()
            self.dismiss("unloaded")
            self.app.notify(f"Model '{self.model_id}' unloaded successfully")
            try:
                models = await client.get_models()
                self._store.models.value = models
            except Exception:
                pass

        except asyncio.CancelledError:
            logger.info(f"Unload of {self.model_id} cancelled")
        except Exception as e:
            logger.error(f"Failed to unload model {self.model_id}: {e}")
            self._show_error(f"Failed to unload: {e}")
            self._stop_loading()

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> Optional[ModelInfo]:
        """Get model info from the store."""
        for model in self._store.models.value:
            if model.id == self.model_id:
                return model
        return None

    def _start_loading(self) -> None:
        """Begin the loading animation and disable Load/Eject buttons."""
        self._loading = True
        self._loading_dots = 0
        self._update_loading_text()
        if self._loading_widget:
            self._loading_widget.display = True
        # Keep Cancel enabled so the user can dismiss during a long load
        for btn in self.query(Button):
            if btn.id != "cancel-btn":
                btn.disabled = True
        self._loading_task = self.set_interval(0.5, self._tick_loading_dots)

    def _tick_loading_dots(self) -> None:
        """Advance the dot counter and refresh the loading label (interval callback)."""
        self._loading_dots = (self._loading_dots + 1) % 4
        self._update_loading_text()

    def _update_loading_text(self) -> None:
        """Update the pre-composed loading Static text."""
        if self._loading_widget:
            dots = "." * self._loading_dots
            self._loading_widget.update(f"⏳ Loading{dots}")

    def _stop_loading(self) -> None:
        """Stop the loading animation and re-enable all buttons."""
        self._loading = False
        if self._loading_task:
            self._loading_task.stop()
            self._loading_task = None
        if self._loading_widget:
            self._loading_widget.display = False
        for btn in self.query(Button):
            btn.disabled = False

    def _show_error(self, message: str) -> None:
        """Display an error message in the pre-composed error widget."""
        if self._error_widget:
            self._error_widget.update(message)
            self._error_widget.display = True
        else:
            logger.error(f"ModelDetailScreen error (no widget): {message}")
