"""Models panel widget for LM Studio TUI.

Displays a table of available models with their load status,
size, quantization, and context length. Supports loading and
unloading models via keybindings. Includes configuration frame
for per-model load options.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from rich.text import Text
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Static, Input, Select, Button

from lmstudio_tui.api.client import LMStudioClient, ModelInfo
from lmstudio_tui.store import get_store, ModelLoadConfig
from lmstudio_tui.utils import format_size, extract_quantization

logger = logging.getLogger(__name__)

# Context length options (truncated to ≤30 chars for compact display)
CONTEXT_OPTIONS = [
    ("8K tokens", 8192),
    ("16K tokens", 16384),
    ("32K tokens", 32768),
    ("65K tokens", 65536),
    ("131K tokens", 131072),
    ("262K tokens", 262144),
    ("Auto (Max VRAM)", -1),  # Special: calculate based on VRAM
    ("Auto (Model Max)", -2),  # Special: use model's max
]

# GPU offload options
OFFLOAD_OPTIONS = [
    ("Max", -1),
    ("100%", 100),
    ("75%", 75),
    ("50%", 50),
    ("25%", 25),
    ("0%", 0),
]

# KV cache quantization options (truncated to ≤30 chars)
KV_QUANT_OPTIONS = [
    ("F16 - Best quality", "f16"),
    ("Q8_0 - Good quality", "q8_0"),
    ("Q4_0 - Smallest", "q4_0"),
]



class ModelsPanel(Container):
    """Panel displaying available models with load/unload controls and config.
    
    Features:
    - DataTable showing Status, Name, Size, Quantization, Context
    - Configuration frame for GPU offload, context length, KV cache quant
    - Loading animation with dots
    - Reactive binding to store.models and store.model_loading
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
    ModelsPanel Static.loading {
        color: $warning;
        text-style: bold;
        content-align: center middle;
        height: 1;
    }
    ModelsPanel Static.config-title {
        text-style: bold;
        color: $secondary;
        height: 1;
        margin-top: 1;
    }
    ModelsPanel Static.config-label {
        color: $text;
        text-style: bold;
        height: 1;
        width: 100%;
        margin-top: 1;
    }
    ModelsPanel Static.config-desc {
        color: $text-muted;
        height: 1;
        width: 100%;
        text-style: italic;
    }
    ModelsPanel Select {
        width: auto;
        min-width: 20;
        max-width: 35;
        margin-top: 0;
        margin-bottom: 0;
    }
    ModelsPanel Static.config-note {
        color: $text-muted;
        text-style: italic;
        height: 1;
        margin-top: 1;
    }
    ModelsPanel Static.vram-estimate {
        height: 1;
        width: 100%;
        content-align: center middle;
        text-style: bold;
    }
    ModelsPanel Static.vram-estimate.green {
        color: $success;
    }
    ModelsPanel Static.vram-estimate.yellow {
        color: $warning;
    }
    ModelsPanel Static.vram-estimate.red {
        color: $error;
    }
    ModelsPanel Button.calculate-btn {
        width: auto;
        min-width: 15;
        margin-top: 1;
        margin-bottom: 0;
    }
    """

    # Reactive state tracking
    _models: reactive[list[ModelInfo]] = reactive(list)
    _error: reactive[Optional[str]] = reactive(None)
    _loading: reactive[Optional[str]] = reactive(None)  # model_id being loaded
    _loading_dots: reactive[int] = reactive(0)
    _selected_model_id: reactive[Optional[str]] = reactive(None)

    def __init__(self, **kwargs):
        """Initialize models panel with store binding."""
        super().__init__(**kwargs)
        self._store = get_store()
        self._table: Optional[DataTable] = None
        self._model_ids: list[str] = []
        self._config_container: Optional[Container] = None
        self._loading_static: Optional[Static] = None
        self._offload_select: Optional[Select] = None
        self._context_select: Optional[Select] = None
        self._kv_quant_select: Optional[Select] = None
        self._vram_estimate_widget: Optional[Static] = None
        self._calculate_btn: Optional[Button] = None
        self._animation_task: Optional[asyncio.Task] = None

    def compose(self):
        """Compose the models panel widgets."""
        yield Static("🤖 MODELS", classes="title")
        
        # Loading indicator
        self._loading_static = Static("", classes="loading")
        self._loading_static.display = False
        yield self._loading_static
        
        # Create data table
        self._table = DataTable()
        self._table.add_columns("Status", "Size", "Model Name")
        self._table.cursor_type = "row"
        self._table.zebra_stripes = True
        yield self._table
        
        # Configuration frame for selected model
        yield Static("⚙️  LOAD CONFIGURATION", classes="config-title")
        self._config_container = Container()
        with self._config_container:
            # GPU Offload (used for memory estimate only; LM Studio manages offload automatically)
            yield Static("GPU Offload (estimate only)", classes="config-label")
            yield Static("For memory estimate — LM Studio auto-manages offload", classes="config-desc")
            self._offload_select = Select(
                OFFLOAD_OPTIONS,
                value=-1,
                id="offload_select"
            )
            yield self._offload_select
            
            # Context Length
            yield Static("Context Length", classes="config-label")
            yield Static("Token window for conversation", classes="config-desc")
            self._context_select = Select(
                CONTEXT_OPTIONS,
                value=8192,
                id="context_select"
            )
            yield self._context_select
            
            # KV Cache Quantization
            yield Static("KV Cache Quant (estimate only)", classes="config-label")
            yield Static("For memory estimate — LM Studio manages KV cache internally", classes="config-desc")
            self._kv_quant_select = Select(
                KV_QUANT_OPTIONS,
                value="f16",
                id="kv_quant_select"
            )
            yield self._kv_quant_select
            
            # Calculate button
            self._calculate_btn = Button("🧮 CALCULATE", id="calculate_btn", classes="calculate-btn")
            yield self._calculate_btn
        
        # VRAM/RAM Estimate row
        yield Static("💾 MEMORY ESTIMATE", classes="config-title")
        self._vram_estimate_widget = Static("Press CALCULATE to see estimate", classes="vram-estimate")
        yield self._vram_estimate_widget
        
        yield Static("Note: Unload + reload required for changes to take effect", classes="config-note")

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
        # Watch for loading state
        self._unwatch_loading = self._store.model_loading.watch(
            self._on_loading_change
        )
        self._unwatch_dots = self._store.model_loading_dots.watch(
            self._on_dots_change
        )
        
        # Initial render if data already available
        initial_models = self._store.models.value
        if initial_models:
            self._models = initial_models
        
        initial_error = self._store.models_error.value
        if initial_error:
            self._error = initial_error
        
        initial_loading = self._store.model_loading.value
        if initial_loading:
            self._loading = initial_loading
        
        # Focus the table for keyboard navigation
        if self._table:
            self._table.focus()

    def on_unmount(self) -> None:
        """Unmount panel and clean up watchers."""
        if hasattr(self, '_unwatch_models'):
            self._unwatch_models()
        if hasattr(self, '_unwatch_error'):
            self._unwatch_error()
        if hasattr(self, '_unwatch_loading'):
            self._unwatch_loading()
        if hasattr(self, '_unwatch_dots'):
            self._unwatch_dots()
        if self._animation_task:
            self._animation_task.cancel()

    def _on_models_change(self, old: list[ModelInfo], new: list[ModelInfo]) -> None:
        """Handle models change from store."""
        self._models = new

    def _on_error_change(self, old: Optional[str], new: Optional[str]) -> None:
        """Handle error change from store."""
        self._error = new

    def _on_loading_change(self, old: Optional[str], new: Optional[str]) -> None:
        """Handle loading state change."""
        self._loading = new
        if new:
            # Start loading animation
            self._start_loading_animation()
        else:
            # Stop loading animation
            self._stop_loading_animation()

    def _on_dots_change(self, old: int, new: int) -> None:
        """Handle dots animation change."""
        if self._loading_static and self._loading:
            dots = "." * (new % 4)
            self._loading_static.update(f"⏳ Loading {self._loading}{dots}")

    def _start_loading_animation(self) -> None:
        """Start the loading animation task."""
        if self._loading_static:
            self._loading_static.display = True
        
        async def animate():
            try:
                while self._loading:
                    await asyncio.sleep(0.5)
                    current = self._store.model_loading_dots.value
                    self._store.model_loading_dots.value = (current + 1) % 4
            except asyncio.CancelledError:
                pass
        
        if self._animation_task:
            self._animation_task.cancel()
        self._animation_task = asyncio.create_task(animate())

    def _stop_loading_animation(self) -> None:
        """Stop the loading animation."""
        if self._loading_static:
            self._loading_static.display = False
        if self._animation_task:
            self._animation_task.cancel()
            self._animation_task = None

    def watch__models(self, models: list[ModelInfo]) -> None:
        """React to models change - rebuild table rows."""
        self._rebuild_table(models)

    def watch__error(self, error: Optional[str]) -> None:
        """React to error change - show error message."""
        if error and self._table:
            self._table.display = False
            for child in self.query(".error"):
                child.remove()
            self.mount(Static(f"Error: {error}", classes="error"))
        elif self._table:
            self._table.display = True
            for child in self.query(".error"):
                child.remove()

    def watch__selected_model_id(self, model_id: Optional[str]) -> None:
        """Update config UI when selection changes."""
        self._update_config_ui(model_id)

    def _update_config_ui(self, model_id: Optional[str]) -> None:
        """Update configuration UI for selected model."""
        if not model_id or not self._offload_select or not self._context_select or not self._kv_quant_select:
            return
        
        config = self._store.get_model_config(model_id)
        
        # Update offload select
        offload_value = config.gpu_offload_percent if config.gpu_offload_percent >= 0 else -1
        try:
            self._offload_select.value = offload_value
        except Exception:
            pass
        
        # Update context select
        context_value = config.context_length if config.context_length > 0 else 8192
        try:
            self._context_select.value = context_value
        except Exception:
            pass
        
        # Update KV quant select
        try:
            self._kv_quant_select.value = config.kv_cache_quantization
        except Exception:
            pass
        
        # Update memory estimate
        self._update_memory_estimate(model_id)
    
    def _calculate_memory_estimate(
        self,
        model: ModelInfo,
        context_length: int,
        gpu_offload_percent: int,
        kv_cache_quantization: str,
    ) -> tuple[float, float]:
        """Estimate VRAM and RAM usage for a model load configuration.
        
        Args:
            model: Model info with size_bytes
            context_length: Context window size in tokens
            gpu_offload_percent: GPU offload percentage (-1 for max)
            kv_cache_quantization: KV cache quantization type (f16, q8_0, q4_0)
            
        Returns:
            Tuple of (estimated_vram_gb, estimated_ram_gb)
        """
        # Model weights memory (in GB)
        model_weights_gb = model.size / (1024 ** 3)
        
        # KV cache KB per token for the whole model (empirically derived)
        # ~100 KB/token for a 4 GB reference model at float16; scales linearly
        kv_kb_per_token = {
            "f16": 100.0,
            "q8_0": 50.0,
            "q4_0": 25.0,
        }.get(kv_cache_quantization, 100.0)

        # Scale KV cost with model size relative to 4 GB reference
        model_size_factor = max(1.0, model_weights_gb / 4.0)
        kv_cache_gb = (context_length * kv_kb_per_token * model_size_factor) / (1024 ** 2)
        
        # Total working memory with overhead
        overhead_gb = 0.5  # Additional overhead for activations, etc.
        total_memory_gb = model_weights_gb + kv_cache_gb + overhead_gb
        
        # Split by GPU offload percentage
        if gpu_offload_percent < 0:  # Max offload
            vram_ratio = 1.0
        else:
            vram_ratio = gpu_offload_percent / 100.0
        
        estimated_vram = total_memory_gb * vram_ratio
        estimated_ram = total_memory_gb * (1.0 - vram_ratio)
        
        return (estimated_vram, estimated_ram)
    
    def _update_memory_estimate(self, model_id: Optional[str] = None) -> None:
        """Update the VRAM/RAM estimate display."""
        if not self._vram_estimate_widget:
            return
        
        if model_id is None:
            model_id = self._get_selected_model_id()
        
        if not model_id:
            self._vram_estimate_widget.update("Select a model to see estimate")
            self._vram_estimate_widget.remove_class("green", "yellow", "red")
            return
        
        # Get model info
        model = self._get_model_by_id(model_id)
        if not model:
            self._vram_estimate_widget.update("Model info not available")
            return
        
        # Get current config
        config = self._store.get_model_config(model_id)
        
        # Calculate estimates
        vram_gb, ram_gb = self._calculate_memory_estimate(
            model=model,
            context_length=config.context_length if config.context_length > 0 else 8192,
            gpu_offload_percent=config.gpu_offload_percent,
            kv_cache_quantization=config.kv_cache_quantization,
        )
        
        # Get available VRAM
        total_vram = sum(g.vram_total for g in self._store.gpu_metrics.value) / 1024
        used_vram = sum(g.vram_used for g in self._store.gpu_metrics.value) / 1024
        available_vram = max(0, total_vram - used_vram)
        
        # Format display
        estimate_text = f"VRAM: {vram_gb:.1f}GB / Available: {available_vram:.1f}GB | RAM: {ram_gb:.1f}GB"
        self._vram_estimate_widget.update(estimate_text)
        
        # Update color based on fit
        self._vram_estimate_widget.remove_class("green", "yellow", "red")
        if vram_gb < available_vram * 0.8:
            self._vram_estimate_widget.add_class("green")
        elif vram_gb <= available_vram:
            self._vram_estimate_widget.add_class("yellow")
        else:
            self._vram_estimate_widget.add_class("red")

    def _rebuild_table(self, models: list[ModelInfo]) -> None:
        """Rebuild table rows based on models."""
        if not self._table:
            return
        
        self._table.clear()
        self._model_ids = []
        
        if not models:
            return
        
        loading_id = self._store.model_loading.value
        
        for model in models:
            # Loaded takes priority — show Loaded even if loading_id matches
            if model.loaded:
                status = "● Loaded"
            elif model.id == loading_id:
                status = "⏳ Loading..."
            else:
                status = "○ Standby"
            
            # Format model size
            size_str = format_size(model.size)
            
            display_name = model.name or model.id
            if len(display_name) > 30:
                display_name = display_name[:27] + "..."
            
            self._table.add_row(status, size_str, display_name)
            self._model_ids.append(model.id)

    def _get_selected_model_id(self) -> Optional[str]:
        """Get the ID of the currently selected model."""
        if not self._table or self._table.cursor_row is None:
            return None
        
        row_idx = self._table.cursor_row
        if 0 <= row_idx < len(self._model_ids):
            return self._model_ids[row_idx]
        return None

    def _get_model_by_id(self, model_id: str) -> Optional[ModelInfo]:
        """Get model info by ID."""
        for model in self._store.models.value:
            if model.id == model_id:
                return model
        return None

    async def action_load_model(self) -> None:
        """Load the selected model with configured options."""
        model_id = self._get_selected_model_id()

        if not model_id:
            self.app.notify("No model selected", severity="warning")
            return

        model = self._get_model_by_id(model_id)

        if model and model.loaded:
            self.app.notify(f"Model '{model.name or model_id}' is already loaded", severity="information")
            return

        # Get configuration for this model
        config = self._store.get_model_config(model_id)
        
        # Determine context length
        if config.context_length == -1:  # Max VRAM
            # Calculate based on available VRAM
            total_vram = sum(g.vram_total for g in self._store.gpu_metrics.value)
            used_vram = sum(g.vram_used for g in self._store.gpu_metrics.value)
            available_vram = max(0, total_vram - used_vram)
            context_length = self._store.calculate_max_context(model_id, available_vram)
        elif config.context_length == -2:  # Max supported
            if model and model.max_context_length > 0:
                context_length = model.max_context_length
            else:
                context_length = 8192
        else:
            context_length = config.context_length

        # Set loading state
        self._store.model_loading.value = model_id
        self.app.notify(f"Loading '{model_id}' with {context_length:,} context...")

        try:
            client = self._store.api_client

            if not client:
                self.app.notify("Not connected to server", severity="error")
                return

            # Load model with configuration
            await client.load_model(
                model_id,
                context_length=context_length,
            )

            # Notify success immediately — API confirmed load
            self.app.notify(f"✓ Model '{model_id}' loaded successfully", severity="information")

            # Refresh model list as best-effort; timeout here is not a load failure
            try:
                models = await client.get_models()
                self._store.models.value = models
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Failed to load model {model_id}: {e}", exc_info=True)
            self.app.notify(f"Failed to load model: {e}", severity="error")
        finally:
            self._store.model_loading.value = None

    async def action_unload_model(self) -> None:
        """Unload the selected model."""
        model_id = self._get_selected_model_id()
        
        if not model_id:
            self.app.notify("No model selected", severity="warning")
            return
        
        model = self._get_model_by_id(model_id)
        
        if model and not model.loaded:
            self.app.notify(f"Model '{model.name or model_id}' is not loaded", severity="information")
            return
        
        if not model or not model.instance_id:
            self.app.notify("No instance ID available for unload", severity="error")
            return
        
        self.app.notify(f"Unloading model '{model_id}'...")
        
        try:
            client = self._store.api_client
            
            if not client:
                self.app.notify("Not connected to server", severity="error")
                return
            
            await client.unload_model(model.instance_id)

            if self._store.active_model.value == model_id:
                self._store.active_model.value = None

            # Notify success immediately — API confirmed unload
            self.app.notify(f"Model '{model_id}' unloaded", severity="information")

            # Refresh model list as best-effort
            try:
                models = await client.get_models()
                self._store.models.value = models
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Failed to unload model {model_id}: {e}", exc_info=True)
            self.app.notify(f"Failed to unload model: {e}", severity="error")

    def action_show_details(self) -> None:
        """Show details for the selected model."""
        model_id = self._get_selected_model_id()
        if not model_id:
            self.app.notify("No model selected", severity="warning")
            return
        
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
        """Handle row selection - update active model and config."""
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._model_ids):
            model_id = self._model_ids[row_idx]
            self._store.set_active_model(model_id)
            self._selected_model_id = model_id

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle config select changes - updates config and memory estimate."""
        model_id = self._get_selected_model_id()
        if not model_id:
            return

        config = self._store.get_model_config(model_id)

        if event.select.id == "offload_select":
            config.gpu_offload_percent = event.value if event.value is not None else -1
        elif event.select.id == "context_select":
            config.context_length = event.value if event.value is not None else 8192
        elif event.select.id == "kv_quant_select":
            config.kv_cache_quantization = event.value if event.value is not None else "f16"

        self._store.set_model_config(model_id, config)

        # Always update memory estimate when any config changes
        self._update_memory_estimate(model_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses - CALCULATE updates memory estimate."""
        if event.button.id == "calculate_btn":
            model_id = self._get_selected_model_id()
            if model_id:
                self._update_memory_estimate(model_id)
                self.app.notify("Memory estimate updated", severity="information")
            else:
                self.app.notify("No model selected", severity="warning")

    def key_l(self) -> None:
        """Handle 'l' key - load model."""
        self.run_worker(self.action_load_model())

    def key_u(self) -> None:
        """Handle 'u' key - unload model."""
        self.run_worker(self.action_unload_model())

    def key_enter(self) -> None:
        """Handle Enter key - show details only when DataTable has focus."""
        if isinstance(self.app.focused, DataTable):
            self.action_show_details()

    def key_r(self) -> None:
        """Handle 'r' key - refresh."""
        self.run_worker(self.action_refresh())
