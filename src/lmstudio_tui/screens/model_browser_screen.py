"""Model browser screen for LM Studio TUI.

Fetches GGUF models from the Hugging Face API and allows the user to
download them via `lms get`. Sort options mirror the LM Studio website.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Select, Static

from lmstudio_tui.store import get_store

logger = logging.getLogger(__name__)

HF_API_URL = "https://huggingface.co/api/models"
HF_SORT_MAP = {
    "downloads": ("downloads", True),   # (api_param, api_handles_sort)
    "likes":     ("likes",     True),
    "createdAt": ("createdAt", True),
    "_size":     ("downloads", False),  # fetched by downloads, re-sorted client-side
}

SORT_OPTIONS = [
    ("Downloads",   "downloads"),
    ("Stars",       "likes"),
    ("Date Created","createdAt"),
    ("Model Size",  "_size"),
]


def _extract_param_billions(model_id: str) -> float:
    """Estimate model parameter count in billions from the repo name.

    Handles patterns like 8B, 70B, 3.8B, 0.5B, 7b, 1.5b.
    Returns 0.0 if not found (sorts to the end).
    """
    match = re.search(r"(\d+\.?\d*)\s*[Bb](?:\b|[^a-z])", model_id)
    return float(match.group(1)) if match else 0.0


class ModelBrowserScreen(ModalScreen[Optional[str]]):
    """Modal screen for browsing and downloading GGUF models from Hugging Face.

    Returns the downloaded model key, or None if closed without downloading.
    """

    DEFAULT_CSS = """
    ModelBrowserScreen {
        align: center middle;
        background: $background 80%;
    }
    ModelBrowserScreen > Container {
        width: 95%;
        height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    ModelBrowserScreen Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        margin-bottom: 1;
    }
    ModelBrowserScreen Static.status {
        color: $text-muted;
        text-style: italic;
        height: 1;
        margin-top: 1;
    }
    ModelBrowserScreen Static.error {
        color: $error;
        height: 1;
        margin-top: 1;
    }
    ModelBrowserScreen DataTable {
        height: 1fr;
        width: 100%;
        border: none;
    }
    ModelBrowserScreen Horizontal.controls {
        height: 3;
        margin-bottom: 1;
    }
    ModelBrowserScreen Select {
        width: 22;
    }
    ModelBrowserScreen Input {
        width: 1fr;
        margin-left: 1;
    }
    ModelBrowserScreen Button.search-btn {
        width: 12;
        margin-left: 1;
    }
    ModelBrowserScreen Horizontal.buttons {
        height: 3;
        margin-top: 1;
        content-align: right middle;
    }
    ModelBrowserScreen Button {
        margin-left: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._store = get_store()
        self._results: list[dict] = []
        self._selected_idx: Optional[int] = None
        self._table: Optional[DataTable] = None
        self._status_widget: Optional[Static] = None
        self._sort_select: Optional[Select] = None
        self._search_input: Optional[Input] = None
        self._download_btn: Optional[Button] = None
        self._current_sort: str = "downloads"

    # ------------------------------------------------------------------
    # Compose / mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("📦 BROWSE MODELS  (Hugging Face · GGUF)", classes="title")

            with Horizontal(classes="controls"):
                self._sort_select = Select(
                    SORT_OPTIONS, value="downloads", id="sort_select"
                )
                yield self._sort_select
                self._search_input = Input(
                    placeholder="Search models…", id="search_input"
                )
                yield self._search_input
                yield Button("🔍 Search", id="search_btn", classes="search-btn")

            self._table = DataTable(id="browser_table")
            self._table.add_columns("Model", "Downloads", "Stars", "Created")
            self._table.cursor_type = "row"
            self._table.zebra_stripes = True
            yield self._table

            self._status_widget = Static("Loading…", classes="status")
            yield self._status_widget

            with Horizontal(classes="buttons"):
                self._download_btn = Button(
                    "⬇ Download", id="download_btn", variant="success", disabled=True
                )
                yield self._download_btn
                yield Button("Close", id="close_btn")

    def on_mount(self) -> None:
        self.run_worker(self._fetch_models("downloads", ""), exclusive=True)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_btn":
            self.dismiss(None)
        elif event.button.id == "search_btn":
            self._trigger_search()
        elif event.button.id == "download_btn":
            self._start_download()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_input":
            self._trigger_search()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sort_select" and event.value:
            self._current_sort = str(event.value)
            search = self._search_input.value.strip() if self._search_input else ""
            self.run_worker(self._fetch_models(self._current_sort, search), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._selected_idx = event.cursor_row
        if self._download_btn:
            self._download_btn.disabled = False

    def key_escape(self) -> None:
        self.dismiss(None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trigger_search(self) -> None:
        search = self._search_input.value.strip() if self._search_input else ""
        self.run_worker(self._fetch_models(self._current_sort, search), exclusive=True)

    def _start_download(self) -> None:
        if self._selected_idx is None or self._selected_idx >= len(self._results):
            return
        model_id = self._results[self._selected_idx]["id"]
        cli = self._store.lms_cli
        if not cli:
            self.app.notify("lms CLI not found — cannot download", severity="error")
            return

        # Prevent concurrent downloads
        from lmstudio_tui.cli.lms_cli import LmsCli
        existing = LmsCli.load_download_state()
        if existing and LmsCli.is_download_running(existing.pid):
            self.app.notify(
                f"Download already in progress: {existing.model_key}",
                severity="warning",
            )
            self.dismiss(None)
            return

        try:
            state = cli.start_download_detached(model_id)
            self.app.notify(f"⬇ Downloading {model_id}… (pid {state.pid})")
            self.dismiss(model_id)
        except Exception as e:
            logger.error(f"Failed to start download for {model_id}: {e}")
            self.app.notify(f"Failed to start download: {e}", severity="error")

    # ------------------------------------------------------------------
    # API fetch
    # ------------------------------------------------------------------

    async def _fetch_models(self, sort: str, search: str) -> None:
        if self._status_widget:
            self._status_widget.update("Loading…")
        if self._download_btn:
            self._download_btn.disabled = True
        self._selected_idx = None

        api_sort, api_handles = HF_SORT_MAP.get(sort, ("downloads", True))

        params = {
            "library": "gguf",
            "sort": api_sort,
            "direction": "-1",
            "limit": "50",
        }
        if search:
            params["search"] = search

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(HF_API_URL, params=params)
                response.raise_for_status()
                data: list[dict] = response.json()
        except Exception as e:
            logger.error(f"HF API error: {e}")
            if self._status_widget:
                self._status_widget.update(f"Failed to load catalog: {e}")
            return

        # Client-side sort for Model Size
        if sort == "_size":
            data.sort(key=lambda m: _extract_param_billions(m.get("id", "")), reverse=True)

        self._results = data
        self._populate_table(data)

        label = f"Showing {len(data)} GGUF models from Hugging Face"
        if search:
            label += f" matching '{search}'"
        if self._status_widget:
            self._status_widget.update(label)

    def _populate_table(self, models: list[dict]) -> None:
        if not self._table:
            return
        self._table.clear()
        for m in models:
            model_id = m.get("id", "")
            downloads = self._fmt_count(m.get("downloads", 0))
            likes = self._fmt_count(m.get("likes", 0))
            created = (m.get("createdAt", "")[:10])  # YYYY-MM-DD
            # Truncate long model IDs
            display_id = model_id if len(model_id) <= 52 else model_id[:49] + "…"
            self._table.add_row(display_id, downloads, likes, created)

    @staticmethod
    def _fmt_count(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)
