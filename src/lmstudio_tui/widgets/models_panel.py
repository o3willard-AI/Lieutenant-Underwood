"""Models panel widget for LM Studio TUI.

Displays a scrollable table of available models with their load status,
size, and name. Pressing Enter opens the model detail/config screen.
Download progress is shown in-panel when active.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Button, DataTable, Static

from lmstudio_tui.api.client import ModelInfo
from lmstudio_tui.store import get_store
from lmstudio_tui.utils import extract_quantization, format_size

logger = logging.getLogger(__name__)

# Re-exported here so existing imports (e.g. tests) continue to resolve.
# The canonical definitions live in model_detail_screen to avoid duplication.
from lmstudio_tui.screens.model_detail_screen import (  # noqa: E402
    CONTEXT_OPTIONS,
    OFFLOAD_OPTIONS,
    TTL_OPTIONS,
)


class ModelsPanel(Container):
    """Panel displaying the available-models list with download status.

    Features:
    - DataTable showing Status, Size, Model Name
    - Loading animation while a model is being loaded
    - Download progress section (hidden until a download is active)
    - Enter key opens ModelDetailScreen for full config + load/unload
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
        height: auto;
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
    ModelsPanel Static.config-note {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }
    ModelsPanel Container.download-status {
        height: auto;
        border: solid $warning;
        padding: 1;
        margin-top: 1;
    }
    ModelsPanel Static.download-title {
        color: $warning;
        text-style: bold;
        height: 1;
        width: 100%;
    }
    ModelsPanel Static.download-model-name {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }
    ModelsPanel Static.download-file-name {
        color: $text;
        text-style: bold;
        height: 1;
    }
    ModelsPanel Static.download-progress-line {
        color: $success;
        height: 1;
    }
    ModelsPanel Static.download-elapsed {
        color: $text-muted;
        text-style: italic;
        height: 1;
    }
    ModelsPanel Button.cancel-download-btn {
        width: auto;
        min-width: 12;
        margin-top: 1;
    }
    """

    _models: reactive[list[ModelInfo]] = reactive(list)
    _error: reactive[Optional[str]] = reactive(None)
    _loading: reactive[Optional[str]] = reactive(None)
    _loading_dots: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        """Initialize models panel with store binding."""
        super().__init__(**kwargs)
        self._store = get_store()
        self._table: Optional[DataTable] = None
        self._model_ids: list[str] = []
        self._loading_static: Optional[Static] = None
        self._animation_task: Optional[asyncio.Task] = None
        self._cli_status_widget: Optional[Static] = None
        # Download status widgets
        self._download_status_container: Optional[Container] = None
        self._download_model_widget: Optional[Static] = None
        self._download_file_widget: Optional[Static] = None
        self._download_progress_widget: Optional[Static] = None
        self._download_elapsed_widget: Optional[Static] = None
        self._download_cancel_btn: Optional[Button] = None

    def compose(self):
        """Compose the models panel widgets."""
        yield Static("🤖 MODELS", classes="title")
        self._cli_status_widget = Static("", id="cli-status", classes="config-note")
        yield self._cli_status_widget

        self._loading_static = Static("", classes="loading")
        self._loading_static.display = False
        yield self._loading_static

        self._table = DataTable()
        self._table.add_columns("Status", "Size", "Model Name")
        self._table.cursor_type = "row"
        self._table.zebra_stripes = True
        yield self._table

        with Container(classes="download-status") as self._download_status_container:
            yield Static("⬇ DOWNLOADING", classes="download-title")
            self._download_model_widget = Static("", classes="download-model-name")
            yield self._download_model_widget
            self._download_file_widget = Static("", classes="download-file-name")
            yield self._download_file_widget
            self._download_progress_widget = Static("", classes="download-progress-line")
            yield self._download_progress_widget
            self._download_elapsed_widget = Static("", classes="download-elapsed")
            yield self._download_elapsed_widget
            self._download_cancel_btn = Button(
                "✗ Cancel",
                id="cancel_download_btn",
                classes="cancel-download-btn",
                variant="error",
            )
            yield self._download_cancel_btn

    def on_mount(self) -> None:
        """Mount panel and set up store watchers."""
        self._unwatch_models = self._store.models.watch(self._on_models_change)
        self._unwatch_error = self._store.models_error.watch(self._on_error_change)
        self._unwatch_loading = self._store.model_loading.watch(self._on_loading_change)
        self._unwatch_dots = self._store.model_loading_dots.watch(self._on_dots_change)

        initial_models = self._store.models.value
        if initial_models:
            self._models = initial_models

        initial_error = self._store.models_error.value
        if initial_error:
            self._error = initial_error

        initial_loading = self._store.model_loading.value
        if initial_loading:
            self._loading = initial_loading

        if self._store.lms_cli:
            if self._cli_status_widget:
                self._cli_status_widget.update("⚡ lms CLI: active")
        else:
            if self._cli_status_widget:
                self._cli_status_widget.update("⚠ lms CLI not found — REST fallback active")

        if self._download_status_container:
            self._download_status_container.display = False

        self._unwatch_download = self._store.download_progress.watch(
            lambda old, new: self._on_download_progress_change(new)
        )
        self._on_download_progress_change(self._store.download_progress.value)

        if self._table:
            self._table.focus()

    def on_unmount(self) -> None:
        """Unmount panel and clean up watchers."""
        if hasattr(self, "_unwatch_models"):
            self._unwatch_models()
        if hasattr(self, "_unwatch_error"):
            self._unwatch_error()
        if hasattr(self, "_unwatch_loading"):
            self._unwatch_loading()
        if hasattr(self, "_unwatch_dots"):
            self._unwatch_dots()
        if hasattr(self, "_unwatch_download"):
            self._unwatch_download()
        if self._animation_task:
            self._animation_task.cancel()

    # ------------------------------------------------------------------
    # Store callbacks
    # ------------------------------------------------------------------

    def _on_models_change(self, old: list[ModelInfo], new: list[ModelInfo]) -> None:
        self._models = new

    def _on_error_change(self, old: Optional[str], new: Optional[str]) -> None:
        self._error = new

    def _on_loading_change(self, old: Optional[str], new: Optional[str]) -> None:
        self._loading = new
        if new:
            self._start_loading_animation()
        else:
            self._stop_loading_animation()

    def _on_dots_change(self, old: int, new: int) -> None:
        if self._loading_static and self._loading:
            dots = "." * (new % 4)
            self._loading_static.update(f"⏳ Loading {self._loading}{dots}")

    # ------------------------------------------------------------------
    # Loading animation
    # ------------------------------------------------------------------

    def _start_loading_animation(self) -> None:
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
        if self._loading_static:
            self._loading_static.display = False
        if self._animation_task:
            self._animation_task.cancel()
            self._animation_task = None

    # ------------------------------------------------------------------
    # Reactive watchers
    # ------------------------------------------------------------------

    def watch__models(self, models: list[ModelInfo]) -> None:
        self._rebuild_table(models)

    def watch__error(self, error: Optional[str]) -> None:
        if error and self._table:
            self._table.display = False
            for child in self.query(".error"):
                child.remove()
            self.mount(Static(f"Error: {error}", classes="error"))
        elif self._table:
            self._table.display = True
            for child in self.query(".error"):
                child.remove()

    # ------------------------------------------------------------------
    # Table management
    # ------------------------------------------------------------------

    def _rebuild_table(self, models: list[ModelInfo]) -> None:
        if not self._table:
            return

        self._table.clear()
        self._model_ids = []

        if not models:
            return

        loading_id = self._store.model_loading.value

        for model in models:
            if model.loaded:
                status = "● Loaded"
            elif model.id == loading_id:
                status = "⏳ Loading..."
            else:
                status = "○ Standby"

            size_str = format_size(model.size)

            display_name = model.name or model.id
            if len(display_name) > 30:
                display_name = display_name[:27] + "..."

            self._table.add_row(status, size_str, display_name)
            self._model_ids.append(model.id)

    def _get_selected_model_id(self) -> Optional[str]:
        if not self._table or self._table.cursor_row is None:
            return None
        row_idx = self._table.cursor_row
        if 0 <= row_idx < len(self._model_ids):
            return self._model_ids[row_idx]
        return None

    def _get_model_by_id(self, model_id: str) -> Optional[ModelInfo]:
        for model in self._store.models.value:
            if model.id == model_id:
                return model
        return None

    # ------------------------------------------------------------------
    # Key handlers
    # ------------------------------------------------------------------

    def key_enter(self) -> None:
        """Open model detail/config screen for the highlighted model."""
        if isinstance(self.app.focused, DataTable):
            self.action_show_details()

    def key_d(self) -> None:
        """Open the Hugging Face model browser."""
        from lmstudio_tui.screens.model_browser_screen import ModelBrowserScreen
        self.app.push_screen(ModelBrowserScreen())

    def key_r(self) -> None:
        """Open the delete model screen."""
        from lmstudio_tui.screens.delete_model_screen import DeleteModelScreen
        self.app.push_screen(DeleteModelScreen())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_show_details(self) -> None:
        """Open ModelDetailScreen for the selected model."""
        model_id = self._get_selected_model_id()
        if not model_id:
            self.app.notify("No model selected", severity="warning")
            return
        from lmstudio_tui.screens.model_detail_screen import ModelDetailScreen
        self.app.push_screen(ModelDetailScreen(model_id))

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Update active model in store on row selection."""
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._model_ids):
            model_id = self._model_ids[row_idx]
            self._store.set_active_model(model_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle download cancel/close button."""
        if event.button.id == "cancel_download_btn":
            prog = self._store.download_progress.value
            if prog and prog.is_running:
                for worker in self.app.workers:
                    if worker.name == "hf_downloader":
                        worker.cancel()
                        break
                self.app.notify("Download cancelled", severity="warning")
            self._store.download_progress.value = None

    def _on_download_progress_change(self, progress) -> None:
        """Show/update the download status section from store state."""
        if not self._download_status_container:
            return

        if progress is None:
            self._download_status_container.display = False
            return

        self._download_status_container.display = True

        if self._download_model_widget:
            repo = progress.model_key
            self._download_model_widget.update(repo if len(repo) <= 55 else repo[:52] + "…")

        if self._download_file_widget:
            fname = progress.filename
            self._download_file_widget.update(fname if len(fname) <= 55 else fname[:52] + "…")

        if self._download_progress_widget:
            line = progress.progress_line
            icon = "⬇" if progress.is_running else ("❌" if progress.error else "✓")
            self._download_progress_widget.update(f"{icon} {line}")

        if self._download_elapsed_widget:
            elapsed = int(progress.elapsed_seconds)
            if elapsed < 60:
                time_str = f"{elapsed}s"
            elif elapsed < 3600:
                time_str = f"{elapsed // 60}m {elapsed % 60}s"
            else:
                time_str = f"{elapsed // 3600}h {(elapsed % 3600) // 60}m"
            self._download_elapsed_widget.update(f"Elapsed: {time_str}")

        if self._download_cancel_btn:
            if progress.is_running:
                self._download_cancel_btn.label = "✗ Cancel"
                self._download_cancel_btn.variant = "error"
            else:
                self._download_cancel_btn.label = "✓ Close"
                self._download_cancel_btn.variant = "default"
            self._download_cancel_btn.disabled = False
