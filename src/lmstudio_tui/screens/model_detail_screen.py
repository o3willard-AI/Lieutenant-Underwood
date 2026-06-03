"""Model detail screen for LM Studio TUI.

Displays detailed information about a model with full load configuration
(GPU offload, context length, TTL) and Load/Unload controls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static

from lmstudio_tui.api.client import ModelInfo
from lmstudio_tui.store import get_store
from lmstudio_tui.utils import format_context_length

logger = logging.getLogger(__name__)

# Context length options
CONTEXT_OPTIONS = [
    ("8K tokens", 8192),
    ("16K tokens", 16384),
    ("32K tokens", 32768),
    ("65K tokens", 65536),
    ("98K tokens", 98304),
    ("131K tokens", 131072),
    ("192K tokens", 196608),
    ("262K tokens", 262144),
    ("Auto (Max VRAM)", -1),
    ("Auto (Model Max)", -2),
]

# GPU offload options — "Max" lets lms pick the highest safe fraction at load time
OFFLOAD_OPTIONS = [
    ("Max", -1),
    ("75%", 75),
    ("50%", 50),
    ("25%", 25),
    ("0% (CPU only)", 0),
]

# TTL auto-unload options
TTL_OPTIONS = [
    ("Off", None),
    ("1 minute", 60),
    ("5 minutes", 300),
    ("30 minutes", 1800),
    ("1 hour", 3600),
]


class ModelDetailScreen(ModalScreen[Optional[str]]):
    """Modal screen showing model details with full load configuration.

    Returns:
        Action taken: "loaded", "unloaded", or None if cancelled.
    """

    DEFAULT_CSS = """
    ModelDetailScreen {
        align: center middle;
        background: $background 80%;
    }
    ModelDetailScreen > Container {
        width: 90;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
        overflow-y: auto;
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
    ModelDetailScreen Static.status-warning {
        color: $warning;
        text-style: bold;
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
    ModelDetailScreen Static.section-title {
        text-style: bold;
        color: $secondary;
        height: 1;
        margin-top: 1;
        width: 100%;
    }
    ModelDetailScreen Static.config-label {
        color: $text;
        text-style: bold;
        height: 1;
        width: 100%;
        margin-top: 1;
    }
    ModelDetailScreen Static.config-desc {
        color: $text-muted;
        height: 1;
        width: 100%;
        text-style: italic;
    }
    ModelDetailScreen Select {
        width: auto;
        min-width: 25;
        max-width: 40;
        margin-top: 0;
    }
    ModelDetailScreen Static.vram-estimate {
        height: 1;
        width: 100%;
        text-style: bold;
    }
    ModelDetailScreen Static.vram-estimate.green {
        color: $success;
    }
    ModelDetailScreen Static.vram-estimate.yellow {
        color: $warning;
    }
    ModelDetailScreen Static.vram-estimate.red {
        color: $error;
    }
    """

    def __init__(self, model_id: str, **kwargs):
        """Initialize the model detail screen."""
        super().__init__(**kwargs)
        self.model_id = model_id
        self._store = get_store()
        self._model: Optional[ModelInfo] = None
        self._loading = False
        self._loading_dots = 0
        self._loading_task = None
        self._loading_widget: Optional[Static] = None
        self._error_widget: Optional[Static] = None
        self._offload_select: Optional[Select] = None
        self._context_select: Optional[Select] = None
        self._ttl_select: Optional[Select] = None
        self._vram_low_widget: Optional[Static] = None
        self._vram_mid_widget: Optional[Static] = None
        self._vram_high_widget: Optional[Static] = None

    # ------------------------------------------------------------------
    # Compose / mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        """Compose the modal content."""
        self._model = self._get_model()
        cfg = self._store.get_model_config(self.model_id) if self._model else None

        with Container():
            yield Static("🤖 Model Details", classes="title")

            if self._model:
                with Horizontal(classes="info-row"):
                    yield Static("Name:", classes="label")
                    yield Static(self._model.name or self._model.id, classes="value")

                if self._model.name and self._model.name != self._model.id:
                    with Horizontal(classes="info-row"):
                        yield Static("ID:", classes="label")
                        yield Static(self._model.id, classes="value")

                status_text = "● Loaded" if self._model.loaded else "○ Standby"
                status_class = "status-loaded" if self._model.loaded else "status-standby"
                with Horizontal(classes="info-row"):
                    yield Static("Status:", classes="label")
                    yield Static(status_text, classes=f"value {status_class}")

                # For loaded models: show actual context window and quantization from LM Studio
                if self._model.loaded:
                    with Horizontal(classes="info-row"):
                        yield Static("Quantization:", classes="label")
                        yield Static(self._model.quantization or "-", classes="value")
                    if self._model.loaded_context_length > 0:
                        actual_label = format_context_length(self._model.loaded_context_length)
                        cfg_ctx = cfg.context_length if cfg and cfg.context_length > 0 else 8192
                        with Horizontal(classes="info-row"):
                            yield Static("Loaded ctx:", classes="label")
                            if self._model.loaded_context_length != cfg_ctx:
                                cfg_label = format_context_length(cfg_ctx)
                                yield Static(
                                    f"{actual_label}  ⚠ TUI configured: {cfg_label}",
                                    classes="value status-warning",
                                )
                            else:
                                yield Static(actual_label, classes="value status-loaded")
                    if self._model.loaded_gpu_offload is not None:
                        with Horizontal(classes="info-row"):
                            yield Static("GPU offload:", classes="label")
                            yield Static(
                                f"{self._model.loaded_gpu_offload * 100:.0f}%",
                                classes="value",
                            )

                # Load configuration section
                yield Static("⚙️  LOAD CONFIGURATION", classes="section-title")

                yield Static("GPU Layer Offload", classes="config-label")
                yield Static(
                    "Fraction of layers on GPU; partial offload allows models larger than VRAM",
                    classes="config-desc",
                )
                offload_value = (cfg.gpu_offload_percent if cfg.gpu_offload_percent >= 0 else -1) if cfg else -1
                self._offload_select = Select(
                    OFFLOAD_OPTIONS,
                    value=offload_value,
                    id="detail_offload_select",
                )
                yield self._offload_select

                yield Static("Context Length", classes="config-label")
                yield Static("Token window for conversation", classes="config-desc")
                context_value = (cfg.context_length if cfg.context_length > 0 else 8192) if cfg else 8192
                self._context_select = Select(
                    CONTEXT_OPTIONS,
                    value=context_value,
                    id="detail_context_select",
                )
                yield self._context_select

                yield Static("Auto-Unload (TTL)", classes="config-label")
                yield Static("Unload model after N seconds of inactivity", classes="config-desc")
                ttl_value = cfg.ttl if cfg else None
                self._ttl_select = Select(
                    TTL_OPTIONS,
                    value=ttl_value,
                    id="detail_ttl_select",
                )
                yield self._ttl_select

                # Memory estimate section
                yield Static("💾 MEMORY ESTIMATE", classes="section-title")
                self._vram_low_widget = Static(
                    "Loading estimate…", classes="vram-estimate", id="detail_vram_low"
                )
                self._vram_mid_widget = Static("", classes="vram-estimate", id="detail_vram_mid")
                self._vram_high_widget = Static("", classes="vram-estimate", id="detail_vram_high")
                yield self._vram_low_widget
                yield self._vram_mid_widget
                yield self._vram_high_widget

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
        """Wire up dynamic widgets and trigger initial memory estimate."""
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
        for btn in self.query(Button):
            btn.disabled = True
        self.call_after_refresh(self._enable_buttons_after_mount)

        # Trigger initial memory estimate
        if self._model:
            self._update_memory_estimate()

    def _enable_buttons_after_mount(self) -> None:
        """Re-enable buttons after first render and restore keyboard focus."""
        if not self._loading:
            for btn in self.query(Button):
                btn.disabled = False
        try:
            self.query_one("#cancel-btn", Button).focus()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id

        if button_id == "load-btn":
            self.run_worker(self._load_model(), exclusive=True)
        elif button_id == "unload-btn":
            self.run_worker(self._unload_model(), exclusive=True)
        elif button_id == "cancel-btn":
            self.dismiss(None)

    def on_select_changed(self, event: Select.Changed) -> None:
        """Persist config changes to store and refresh memory estimate."""
        config = self._store.get_model_config(self.model_id)

        if event.select.id == "detail_offload_select":
            config.gpu_offload_percent = event.value if event.value is not None else -1
        elif event.select.id == "detail_context_select":
            config.context_length = event.value if event.value is not None else 8192
        elif event.select.id == "detail_ttl_select":
            config.ttl = event.value

        self._store.set_model_config(self.model_id, config)
        self._update_memory_estimate()

    def key_escape(self) -> None:
        """Handle Escape key - close modal."""
        self.dismiss(None)

    def key_tab(self) -> None:
        """Tab cycles focus forward through enabled buttons."""
        self._cycle_focus(forward=True)

    def key_shift_tab(self) -> None:
        """Shift-Tab cycles focus backward through enabled buttons."""
        self._cycle_focus(forward=False)

    def key_right(self) -> None:
        """Right arrow moves focus to next button."""
        self._cycle_focus(forward=True)

    def key_left(self) -> None:
        """Left arrow moves focus to previous button."""
        self._cycle_focus(forward=False)

    def _cycle_focus(self, forward: bool) -> None:
        """Cycle keyboard focus among the enabled buttons."""
        buttons = [b for b in self.query(Button) if not b.disabled]
        if len(buttons) < 2:
            return
        try:
            idx = buttons.index(self.focused)
        except ValueError:
            idx = -1
        buttons[(idx + (1 if forward else -1)) % len(buttons)].focus()

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

            # Record what we're requesting so we can compare against what LM Studio actually loads
            self._store.record_load_request(
                self.model_id, context_length, config.gpu_offload_percent
            )

            cli = self._store.lms_cli
            if cli:
                await cli.load_model(
                    model_key=self.model_id,
                    context_length=context_length,
                    gpu_offload_percent=config.gpu_offload_percent,
                    ttl=config.ttl,
                )
            else:
                await client.load_model(
                    self.model_id,
                    context_length=context_length,
                    kv_cache_quantization=config.kv_cache_quantization,
                )

            # Refresh model list and compute actual vs requested delta BEFORE dismissing
            delta = None
            try:
                models = await client.get_models()
                self._store.models.value = models
                for m in models:
                    if m.id == self.model_id:
                        delta = self._store.check_and_log_load_delta(m)
                        break
            except Exception:
                pass

            self._stop_loading()
            self.app.notify(f"Model '{self.model_id}' loaded successfully")

            if delta and delta["context_delta"] != 0 and delta["actual_context"] > 0:
                actual_label = format_context_length(delta["actual_context"])
                req_label = format_context_length(delta["requested_context"])
                self.app.notify(
                    f"Context: requested {req_label} → LM Studio loaded {actual_label} "
                    f"({delta['context_delta']:+,} tokens / {delta['context_delta_pct']:+.1f}%)",
                    severity="warning",
                    timeout=12,
                )

            self.dismiss("loaded")

        except asyncio.CancelledError:
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
    # Memory estimate
    # ------------------------------------------------------------------

    def _calculate_memory_estimate(
        self,
        model: ModelInfo,
        context_length: int,
        gpu_offload_percent: int,
        kv_cache_quantization: str,
    ) -> tuple[float, float]:
        """Return (estimated_vram_gb, estimated_ram_gb) for the given config."""
        model_weights_gb = model.size / (1024 ** 3)
        kv_kb_per_token = {"f16": 100.0, "q8_0": 50.0, "q4_0": 25.0}.get(
            kv_cache_quantization, 100.0
        )
        model_size_factor = max(1.0, model_weights_gb / 4.0)
        kv_cache_gb = (context_length * kv_kb_per_token * model_size_factor) / (1024 ** 2)
        overhead_gb = 0.5
        total_memory_gb = model_weights_gb + kv_cache_gb + overhead_gb

        vram_ratio = 1.0 if gpu_offload_percent < 0 else gpu_offload_percent / 100.0
        return total_memory_gb * vram_ratio, total_memory_gb * (1.0 - vram_ratio)

    def _update_memory_estimate(self) -> None:
        """Refresh the three VRAM estimate rows (low/mid/high quant)."""
        if not self._vram_low_widget:
            return

        if not self._model:
            self._vram_low_widget.update("No model selected")
            if self._vram_mid_widget:
                self._vram_mid_widget.update("")
            if self._vram_high_widget:
                self._vram_high_widget.update("")
            return

        config = self._store.get_model_config(self.model_id)
        ctx = config.context_length if config.context_length > 0 else 8192
        offload = config.gpu_offload_percent

        total_vram = sum(g.vram_total for g in self._store.gpu_metrics.value) / 1024
        used_vram = sum(g.vram_used for g in self._store.gpu_metrics.value) / 1024
        available_vram = max(0, total_vram - used_vram)

        quant_rows = [
            ("Q4_0 Low ", "q4_0", self._vram_low_widget),
            ("Q8_0 Mid ", "q8_0", self._vram_mid_widget),
            (" F16 High", "f16",  self._vram_high_widget),
        ]

        for label, quant, widget in quant_rows:
            if widget is None:
                continue
            vram_gb, ram_gb = self._calculate_memory_estimate(
                model=self._model,
                context_length=ctx,
                gpu_offload_percent=offload,
                kv_cache_quantization=quant,
            )
            text = (
                f"{label}: {vram_gb:.1f}GB VRAM / {available_vram:.1f}GB avail"
                f" | {ram_gb:.1f}GB RAM"
            )
            widget.update(text)
            widget.remove_class("green", "yellow", "red")
            if vram_gb < available_vram * 0.8:
                widget.add_class("green")
            elif vram_gb <= available_vram:
                widget.add_class("yellow")
            else:
                widget.add_class("red")

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
        for btn in self.query(Button):
            if btn.id != "cancel-btn":
                btn.disabled = True
        self._loading_task = self.set_interval(0.5, self._tick_loading_dots)

    def _tick_loading_dots(self) -> None:
        """Advance the dot counter and refresh the loading label."""
        self._loading_dots = (self._loading_dots + 1) % 4
        self._update_loading_text()

    def _update_loading_text(self) -> None:
        """Update the loading Static text."""
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
        """Display an error message in the error widget."""
        if self._error_widget:
            self._error_widget.update(message)
            self._error_widget.display = True
        else:
            logger.error(f"ModelDetailScreen error (no widget): {message}")
