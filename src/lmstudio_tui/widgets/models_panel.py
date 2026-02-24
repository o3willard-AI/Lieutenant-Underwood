"""Models panel widget for LM Studio TUI.

Displays a table of available models with their load status,
size, quantization, and context length. Supports loading and
unloading models via keybindings.
"""

from __future__ import annotations

import logging
from typing import Optional

from rich.text import Text
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Static

from lmstudio_tui.api.client import LMStudioClient, ModelInfo
from lmstudio_tui.store import get_store

logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human-readable string.
    
    Args:
        size_bytes: Size in bytes.
        
    Returns:
        Human-readable string (e.g., "42.5 GB", "512 MB").
    """
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"


def extract_quantization(model_name: str) -> str:
    """Extract quantization from model name.
    
    Args:
        model_name: Model name string.
        
    Returns:
        Quantization string (e.g., "Q4_K_M") or "-".
    """
    # Common quantization patterns
    import re
    patterns = [
        r'-(Q\d+_[KMS]_[ML]?)',  # Q4_K_M, Q5_K_S, Q6_K etc.
        r'-(Q\d+_[KMS])',        # Q4_K, Q5_K, Q4_S etc.
        r'-(Q\d+[A-Z]?)',        # Q4, Q5, Q8_0 etc.
        r'-(FP16)',
        r'-(FP32)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, model_name, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return "-"


class ModelsPanel(Container):
    """Panel displaying available models with load/unload controls.
    
    Features:
    - DataTable showing Status, Name, Size, Quantization, Context
    - Reactive binding to store.models
    - Keybindings: l (load), u (unload), Enter (details), r (refresh)
    """

    DEFAULT_CSS = """
    ModelsPanel {
        width: 100%;
        height: auto;
        padding: 1;
        border: solid $primary;
    }
    ModelsPanel Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        content-align: left middle;
    }
    ModelsPanel DataTable {
        width: 100%;
        height: 1fr;
        border: none;
    }
    ModelsPanel DataTable > .datatable--header {
        text-style: bold;
        background: $surface;
        color: $primary;
    }
    ModelsPanel DataTable > .datatable--row {
        height: 1;
    }
    ModelsPanel DataTable > .datatable--row-cursor {
        background: $primary-darken-2;
    }
    ModelsPanel Static.help-text {
        color: $text-muted;
        height: 1;
        content-align: left middle;
    }
    ModelsPanel Static.error {
        color: $error;
        text-style: bold;
        content-align: center middle;
        height: 3;
    }
    ModelsPanel Static.no-models {
        color: $text-muted;
        content-align: center middle;
        height: 3;
    }
    """

    # Reactive state tracking
    _models: reactive[list[ModelInfo]] = reactive(list)
    _error: reactive[Optional[str]] = reactive(None)
    _loading: reactive[bool] = reactive(False)

    def __init__(self, **kwargs):
        """Initialize models panel with store binding."""
        super().__init__(**kwargs)
        self._store = get_store()
        self._table: Optional[DataTable] = None
        self._model_ids: list[str] = []  # Track model IDs for row mapping

    def compose(self):
        """Compose the models panel widgets."""
        yield Static("🤖 MODELS", classes="title")
        
        # Create data table
        self._table = DataTable()
        self._table.add_columns("Status", "Model Name")
        self._table.cursor_type = "row"
        self._table.zebra_stripes = True
        yield self._table
        
        yield Static("[Enter] Details │ [l] Load │ [u] Unload │ [r] Refresh", classes="help-text")

    def on_mount(self) -> None:
        """Mount panel and set up store watchers."""
        # Watch for models changes
        self._unwatch_models = self._store.models.watch(
            self._on_models_change
        )
        # Watch for errors
        self._unwatch_error = self._store.models_error.watch(
            self._on_error_change
        )
        
        # Initial render if data already available
        initial_models = self._store.models.value
        if initial_models:
            self._models = initial_models
        
        initial_error = self._store.models_error.value
        if initial_error:
            self._error = initial_error
        
        # Focus the table for keyboard navigation
        if self._table:
            self._table.focus()

    def on_unmount(self) -> None:
        """Unmount panel and clean up watchers."""
        if hasattr(self, '_unwatch_models'):
            self._unwatch_models()
        if hasattr(self, '_unwatch_error'):
            self._unwatch_error()

    def _on_models_change(self, old: list[ModelInfo], new: list[ModelInfo]) -> None:
        """Handle models change from store.
        
        Args:
            old: Previous models list.
            new: New models list.
        """
        self._models = new

    def _on_error_change(self, old: Optional[str], new: Optional[str]) -> None:
        """Handle error change from store.
        
        Args:
            old: Previous error (if any).
            new: New error (if any).
        """
        self._error = new

    def watch__models(self, models: list[ModelInfo]) -> None:
        """React to models change - rebuild table rows."""
        self._rebuild_table(models)

    def watch__error(self, error: Optional[str]) -> None:
        """React to error change - show error message."""
        if error and self._table:
            self._table.display = False
            # Remove any existing error static
            for child in self.query(".error"):
                child.remove()
            self.mount(Static(f"Error: {error}", classes="error"))
        elif self._table:
            self._table.display = True
            for child in self.query(".error"):
                child.remove()

    def watch__loading(self, loading: bool) -> None:
        """Update UI based on loading state."""
        if loading:
            # Could add a loading indicator here
            pass

    def _rebuild_table(self, models: list[ModelInfo]) -> None:
        """Rebuild table rows based on models.
        
        Args:
            models: List of ModelInfo to display.
        """
        if not self._table:
            return
        
        # Clear existing rows
        self._table.clear()
        self._model_ids = []
        
        if not models:
            return
        
        # Add rows for each model
        for model in models:
            status = "● Loaded" if model.loaded else "○ Standby"
            size_str = format_size(model.size) if model.size > 0 else "-"
            quant = model.quantization if model.quantization != "-" else extract_quantization(model.id)
            # Show loaded context / max context
            if model.loaded and model.loaded_context_length > 0:
                context = f"{model.loaded_context_length:,}"
            elif model.max_context_length > 0:
                context = f"{model.max_context_length:,}"
            else:
                context = "-"
            
            # Truncate model name if too long - allow 4 more chars
            display_name = model.name or model.id
            if len(display_name) > 34:
                display_name = display_name[:31] + "..."
            
            self._table.add_row(
                status,
                display_name
            )
            self._model_ids.append(model.id)

    def _get_selected_model_id(self) -> Optional[str]:
        """Get the ID of the currently selected model.
        
        Returns:
            Model ID if a row is selected, None otherwise.
        """
        if not self._table or self._table.cursor_row is None:
            return None
        
        row_idx = self._table.cursor_row
        if 0 <= row_idx < len(self._model_ids):
            return self._model_ids[row_idx]
        return None

    def _get_model_by_id(self, model_id: str) -> Optional[ModelInfo]:
        """Get model info by ID.
        
        Args:
            model_id: Model identifier.
            
        Returns:
            ModelInfo if found, None otherwise.
        """
        for model in self._store.models.value:
            if model.id == model_id:
                return model
        return None

    async def action_load_model(self) -> None:
        """Load the selected model."""
        logger.info("=== action_load_model called ===")
        model_id = self._get_selected_model_id()
        logger.info(f"Selected model_id: {model_id}")

        if not model_id:
            self.app.notify("No model selected", severity="warning")
            logger.warning("No model selected")
            return

        model = self._get_model_by_id(model_id)
        logger.info(f"Found model: {model}")

        if model and model.loaded:
            self.app.notify(f"Model '{model.name or model_id}' is already loaded", severity="information")
            logger.info(f"Model already loaded: {model_id}")
            return

        self._loading = True
        self.app.notify(f"Loading model '{model_id}'...")
        logger.info(f"Starting load for model: {model_id}")

        try:
            client = self._store.api_client
            logger.info(f"API client: {client}")

            if not client:
                self.app.notify("Not connected to server", severity="error")
                logger.error("No API client - not connected")
                return

            # Use max context length from model info for optimal VRAM usage
            context_length = model.max_context_length if model else None
            if context_length and context_length > 0:
                logger.info(f"Using max_context_length={context_length} for load")
            else:
                context_length = None
                logger.info("No max_context_length available, letting API use default")

            logger.info(f"Calling client.load_model({model_id}, context_length={context_length})")
            result = await client.load_model(model_id, context_length=context_length)
            logger.info(f"load_model result: {result}")

            self.app.notify(f"Model '{model_id}' loaded successfully", severity="information")

            # Trigger a refresh
            logger.info("Refreshing models after load")
            await self._refresh_models()

        except Exception as e:
            logger.error(f"Failed to load model {model_id}: {e}", exc_info=True)
            self.app.notify(f"Failed to load model: {e}", severity="error")
        finally:
            self._loading = False
            logger.info("=== action_load_model complete ===")

    async def action_unload_model(self) -> None:
        """Unload the selected model."""
        logger.info("=== action_unload_model called ===")
        model_id = self._get_selected_model_id()
        logger.info(f"Selected model_id for unload: {model_id}")
        
        if not model_id:
            self.app.notify("No model selected", severity="warning")
            logger.warning("No model selected for unload")
            return
        
        model = self._get_model_by_id(model_id)
        logger.info(f"Found model for unload: {model}, loaded={model.loaded if model else 'N/A'}")
        
        if model and not model.loaded:
            self.app.notify(f"Model '{model.name or model_id}' is not loaded", severity="information")
            logger.info(f"Model not loaded, skipping unload: {model_id}")
            return
        
        if not model or not model.instance_id:
            self.app.notify("No instance ID available for unload", severity="error")
            logger.error(f"No instance_id for model: {model_id}")
            return
        
        self._loading = True
        self.app.notify(f"Unloading model '{model_id}'...")
        logger.info(f"Starting unload for model: {model_id} with instance_id: {model.instance_id}")
        
        try:
            client = self._store.api_client
            logger.info(f"API client for unload: {client}")
            
            if not client:
                self.app.notify("Not connected to server", severity="error")
                logger.error("No API client - not connected for unload")
                return
            
            logger.info(f"Calling client.unload_model(instance_id={model.instance_id})")
            result = await client.unload_model(model.instance_id)
            logger.info(f"unload_model result: {result}")
            
            self.app.notify(f"Model '{model_id}' unloaded successfully", severity="information")
            logger.info(f"Unload success for {model_id}")
            
            # Clear active model if it was this one
            if self._store.active_model.value == model_id:
                self._store.active_model.value = None
                logger.info(f"Cleared active model: {model_id}")
            
            # Trigger a refresh
            logger.info("Refreshing models after unload")
            await self._refresh_models()
            
        except Exception as e:
            logger.error(f"Failed to unload model {model_id}: {e}", exc_info=True)
            self.app.notify(f"Failed to unload model: {e}", severity="error")
        finally:
            self._loading = False
            logger.info("=== action_unload_model complete ===")

    def action_show_details(self) -> None:
        """Show details for the selected model."""
        model_id = self._get_selected_model_id()
        if not model_id:
            self.app.notify("No model selected", severity="warning")
            return
        
        # Import here to avoid circular imports
        from lmstudio_tui.screens.model_detail_screen import ModelDetailScreen
        self.app.push_screen(ModelDetailScreen(model_id))

    async def action_refresh(self) -> None:
        """Refresh the models list."""
        await self._refresh_models()
        self.app.notify("Models refreshed")

    async def _refresh_models(self) -> None:
        """Fetch fresh models from the API."""
        try:
            client = self._store.api_client
            if not client:
                self.app.notify("Not connected to server", severity="error")
                return
            
            models = await client.get_models()
            self._store.models.value = models
            self._store.models_error.value = None
            
        except Exception as e:
            logger.error(f"Failed to refresh models: {e}")
            self._store.models_error.value = str(e)
            self.app.notify(f"Failed to refresh: {e}", severity="error")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection - update active model.
        
        Args:
            event: Row selection event.
        """
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._model_ids):
            model_id = self._model_ids[row_idx]
            self._store.set_active_model(model_id)

    def key_l(self) -> None:
        """Handle 'l' key - load model."""
        self.run_worker(self.action_load_model())

    def key_u(self) -> None:
        """Handle 'u' key - unload model."""
        self.run_worker(self.action_unload_model())

    def key_enter(self) -> None:
        """Handle Enter key - show details."""
        self.action_show_details()

    def key_r(self) -> None:
        """Handle 'r' key - refresh."""
        self.run_worker(self.action_refresh())
