"""Model detail screen for LM Studio TUI.

Displays detailed information about a model with Load/Unload controls.
This is a modal screen that appears when the user selects a model
and presses Enter.
"""

from __future__ import annotations

import logging
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from lmstudio_tui.api.client import ModelInfo
from lmstudio_tui.store import get_store
from lmstudio_tui.widgets.models_panel import format_size, extract_quantization

logger = logging.getLogger(__name__)


class ModelDetailScreen(ModalScreen[Optional[str]]):
    """Modal screen showing model details with Load/Unload controls.
    
    This screen displays:
    - Model name and ID
    - Size and quantization info
    - Current load status
    - Load/Unload buttons
    
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
        max-height: 20;
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
        color: $text-secondary;
        width: 12;
    }
    ModelDetailScreen Static.value {
        color: $text-primary;
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
    ModelDetailScreen Button.success {
        background: $success;
        color: $text-primary;
    }
    ModelDetailScreen Button.error {
        background: $error;
        color: $text-primary;
    }
    """

    def __init__(self, model_id: str, **kwargs):
        """Initialize the model detail screen.
        
        Args:
            model_id: ID of the model to display.
            **kwargs: Additional arguments passed to ModalScreen.
        """
        super().__init__(**kwargs)
        self.model_id = model_id
        self._store = get_store()
        self._model: Optional[ModelInfo] = None
        self._error: Optional[str] = None
        self._ignore_enter = True  # Ignore first Enter key to prevent auto-fire
        self._loading = False  # Loading state for load/unload operations
        self._loading_dots = 0  # Counter for animated dots
        self._loading_task = None  # Timer task for animation

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        with Container():
            yield Static("🤖 Model Details", classes="title")
            
            # Get model info
            self._model = self._get_model()
            
            if self._model:
                # Model name/ID
                with Horizontal(classes="info-row"):
                    yield Static("Name:", classes="label")
                    yield Static(self._model.name or self._model.id, classes="value")
                
                # Model ID (if different from name)
                if self._model.name and self._model.name != self._model.id:
                    with Horizontal(classes="info-row"):
                        yield Static("ID:", classes="label")
                        yield Static(self._model.id, classes="value")
                
                # Quantization
                quant = self._model.quantization if self._model.quantization != "-" else extract_quantization(self._model.id)
                with Horizontal(classes="info-row"):
                    yield Static("Quant:", classes="label")
                    yield Static(quant, classes="value")
                
                # Context Length
                if self._model.loaded and self._model.loaded_context_length > 0:
                    context_text = f"{self._model.loaded_context_length:,} / {self._model.max_context_length:,}"
                elif self._model.max_context_length > 0:
                    context_text = f"{self._model.max_context_length:,}"
                else:
                    context_text = "-"
                with Horizontal(classes="info-row"):
                    yield Static("Context:", classes="label")
                    yield Static(context_text, classes="value")
                
                # Status
                status_text = "● Loaded" if self._model.loaded else "○ Standby"
                status_class = "status-loaded" if self._model.loaded else "status-standby"
                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="label")
                    yield Static(status_text, classes=f"value {status_class}")
                
                # Buttons - Cancel first to prevent accidental action
                with Horizontal(classes="buttons"):
                    yield Button("Cancel", id="cancel-btn")
                    if self._model.loaded:
                        yield Button(
                            "Eject",
                            id="unload-btn",
                            variant="error"
                        )
                        yield Button(
                            "Change Context",
                            id="context-btn",
                            variant="primary"
                        )
                    else:
                        yield Button(
                            "Load",
                            id="load-btn",
                            variant="success"
                        )
            else:
                yield Static(f"Model '{self.model_id}' not found", classes="error")
                with Horizontal(classes="buttons"):
                    yield Button("Close", id="cancel-btn")
            
            # Error message (conditional)
            if self._error:
                yield Static(self._error, classes="error")

    def _get_model(self) -> Optional[ModelInfo]:
        """Get model info from store.
        
        Returns:
            ModelInfo if found, None otherwise.
        """
        for model in self._store.models.value:
            if model.id == self.model_id:
                return model
        return None

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.
        
        Args:
            event: Button press event.
        """
        button_id = event.button.id
        
        if button_id == "load-btn":
            await self._load_model()
        elif button_id == "unload-btn":
            await self._unload_model()
        elif button_id == "context-btn":
            await self._change_context()
        elif button_id == "cancel-btn":
            self.dismiss(None)

    async def _change_context(self) -> None:
        """Change the model's context window size."""
        # Placeholder - would open a dialog to adjust context
        self.app.notify("Context change not yet implemented - use LM Studio desktop UI", severity="warning")

    async def _load_model(self) -> None:
        """Load the model with animated loading state."""
        if not self._model:
            return
        
        if self._model.loaded:
            self._error = "Model is already loaded"
            self._update_error_display()
            return
        
        if self._loading:
            return  # Prevent duplicate requests
        
        self._loading = True
        self._loading_dots = 0
        self._update_loading_display()
        self._disable_buttons()
        
        # Start animated dots timer
        self._loading_task = self.set_interval(0.5, self._animate_loading_dots)
        
        try:
            client = self._store.api_client
            if not client:
                self._error = "Not connected to server"
                self._update_error_display()
                self._stop_loading()
                return
            
            await client.load_model(self.model_id)
            
            # Refresh models list
            models = await client.get_models()
            self._store.models.value = models
            
            self._stop_loading()
            self.dismiss("loaded")
            self.app.notify(f"Model '{self.model_id}' loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load model {self.model_id}: {e}")
            self._error = f"Failed to load: {e}"
            self._update_error_display()
            self._stop_loading()

    async def _unload_model(self) -> None:
        """Unload the model with animated loading state."""
        if not self._model:
            return
        
        if not self._model.loaded:
            self._error = "Model is not loaded"
            self._update_error_display()
            return
        
        if not self._model.instance_id:
            self._error = "No instance ID available"
            self._update_error_display()
            return
        
        if self._loading:
            return  # Prevent duplicate requests
        
        self._loading = True
        self._loading_dots = 0
        self._update_loading_display()
        self._disable_buttons()
        
        # Start animated dots timer
        self._loading_task = self.set_interval(0.5, self._animate_loading_dots)
        
        try:
            client = self._store.api_client
            if not client:
                self._error = "Not connected to server"
                self._update_error_display()
                self._stop_loading()
                return
            
            await client.unload_model(self._model.instance_id)
            
            # Clear active model if it was this one
            if self._store.active_model.value == self.model_id:
                self._store.active_model.value = None
            
            # Refresh models list
            models = await client.get_models()
            self._store.models.value = models
            
            self._stop_loading()
            self.dismiss("unloaded")
            self.app.notify(f"Model '{self.model_id}' unloaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to unload model {self.model_id}: {e}")
            self._error = f"Failed to unload: {e}"
            self._update_error_display()
            self._stop_loading()

    def _animate_loading_dots(self) -> None:
        """Animate the loading dots (runs every 0.5 seconds)."""
        self._loading_dots = (self._loading_dots + 1) % 4  # 0, 1, 2, 3, 0...
        self._update_loading_display()

    def _update_loading_display(self) -> None:
        """Update the loading text with animated dots."""
        # Remove existing loading indicator
        for child in self.query("Static.loading"):
            child.remove()
        
        if self._loading:
            # Add animated loading text
            dots = "." * self._loading_dots
            container = self.query_one(Container)
            loading_text = f"⏳ Loading{dots}"
            loading_static = Static(loading_text, classes="loading")
            # Insert before buttons
            buttons = self.query_one("Horizontal.buttons")
            buttons.mount(loading_static, before=0)

    def _disable_buttons(self) -> None:
        """Disable all buttons during loading."""
        for button in self.query(Button):
            button.disabled = True

    def _stop_loading(self) -> None:
        """Stop the loading animation and re-enable buttons."""
        self._loading = False
        
        # Stop the animation timer
        if self._loading_task:
            self._loading_task.stop()
            self._loading_task = None
        
        # Remove loading indicator
        for child in self.query("Static.loading"):
            child.remove()
        
        # Re-enable buttons
        for button in self.query(Button):
            button.disabled = False

    def _update_error_display(self) -> None:
        """Update the error display."""
        # Remove existing error
        for child in self.query("Static.error"):
            child.remove()
        
        # Add new error if present
        if self._error:
            # Find the container and add error before buttons
            container = self.query_one(Container)
            error_static = Static(self._error, classes="error")
            container.mount(error_static)

    def key_escape(self) -> None:
        """Handle Escape key - close modal."""
        self.dismiss(None)

    def on_mount(self) -> None:
        """Set a flag to ignore the first enter key press."""
        self._ignore_enter = True

    def key_enter(self) -> None:
        """Handle Enter key - ignore first press to prevent auto-fire."""
        if self._ignore_enter:
            self._ignore_enter = False
            return
        # Let focused button handle Enter

    def key_tab(self) -> None:
        """Handle Tab key - move focus to next button."""
        self.screen.focus_next()
        self._ignore_enter = False  # User has interacted, stop ignoring

    def key_shift_tab(self) -> None:
        """Handle Shift+Tab - move focus to previous button."""
        self.screen.focus_previous()
        self._ignore_enter = False  # User has interacted, stop ignoring
