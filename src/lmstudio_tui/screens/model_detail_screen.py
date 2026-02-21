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
                
                # Size
                with Horizontal(classes="info-row"):
                    yield Static("Size:", classes="label")
                    yield Static(format_size(self._model.size), classes="value")
                
                # Quantization
                quant = extract_quantization(self._model.id)
                with Horizontal(classes="info-row"):
                    yield Static("Quant:", classes="label")
                    yield Static(quant, classes="value")
                
                # Status
                status_text = "● Loaded" if self._model.loaded else "○ Standby"
                status_class = "status-loaded" if self._model.loaded else "status-standby"
                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="label")
                    yield Static(status_text, classes=f"value {status_class}")
                
                # Buttons
                with Horizontal(classes="buttons"):
                    if self._model.loaded:
                        yield Button(
                            "Unload Model",
                            id="unload-btn",
                            variant="error"
                        )
                    else:
                        yield Button(
                            "Load Model",
                            id="load-btn",
                            variant="success"
                        )
                    yield Button("Cancel", id="cancel-btn")
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
        elif button_id == "cancel-btn":
            self.dismiss(None)

    async def _load_model(self) -> None:
        """Load the model."""
        if not self._model:
            return
        
        if self._model.loaded:
            self._error = "Model is already loaded"
            self._update_error_display()
            return
        
        try:
            client = self._store.api_client
            if not client:
                self._error = "Not connected to server"
                self._update_error_display()
                return
            
            await client.load_model(self.model_id)
            
            # Refresh models list
            models = await client.get_models()
            self._store.models.value = models
            
            self.dismiss("loaded")
            self.app.notify(f"Model '{self.model_id}' loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load model {self.model_id}: {e}")
            self._error = f"Failed to load: {e}"
            self._update_error_display()

    async def _unload_model(self) -> None:
        """Unload the model."""
        if not self._model:
            return
        
        if not self._model.loaded:
            self._error = "Model is not loaded"
            self._update_error_display()
            return
        
        try:
            client = self._store.api_client
            if not client:
                self._error = "Not connected to server"
                self._update_error_display()
                return
            
            await client.unload_model(self.model_id)
            
            # Clear active model if it was this one
            if self._store.active_model.value == self.model_id:
                self._store.active_model.value = None
            
            # Refresh models list
            models = await client.get_models()
            self._store.models.value = models
            
            self.dismiss("unloaded")
            self.app.notify(f"Model '{self.model_id}' unloaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to unload model {self.model_id}: {e}")
            self._error = f"Failed to unload: {e}"
            self._update_error_display()

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
