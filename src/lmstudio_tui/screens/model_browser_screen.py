"""Model browser screen for LM Studio TUI.

Fetches GGUF model repos from the Hugging Face API and, after the user selects
a specific quantization file, downloads it directly via httpx streaming.

Download flow (two-step to handle multi-file GGUF repos):
  1. BROWSE mode — search/sort HF repos, pick a repo row.
  2. PICKING mode — fetch that repo's GGUF file list, pick a specific variant.
  3. Stream download starts as an app-level worker (survives modal dismissal).
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
    "downloads": ("downloads", True),
    "likes":     ("likes",     True),
    "createdAt": ("createdAt", True),
    "_size":     ("downloads", False),  # client-side re-sort by param count
}

SORT_OPTIONS = [
    ("Downloads",    "downloads"),
    ("Stars",        "likes"),
    ("Date Created", "createdAt"),
    ("Model Size",   "_size"),
]


def _extract_param_billions(model_id: str) -> float:
    match = re.search(r"(\d+\.?\d*)\s*[Bb](?:\b|[^a-z])", model_id)
    return float(match.group(1)) if match else 0.0


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.0f} MB"
    if size_bytes > 0:
        return f"{size_bytes / 1024:.0f} KB"
    return "?"


class ModelBrowserScreen(ModalScreen[Optional[str]]):
    """Modal screen for browsing HF GGUF repos and downloading a chosen variant.

    Returns the HF repo ID of the model whose download was started, or None
    if the screen was closed without initiating a download.
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
    ModelBrowserScreen #browse_pane {
        height: 1fr;
        width: 100%;
    }
    ModelBrowserScreen #picker_pane {
        height: 1fr;
        width: 100%;
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
    ModelBrowserScreen Static.picker-header {
        color: $text-muted;
        text-style: italic;
        height: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._store = get_store()

        # Browse mode state
        self._results: list[dict] = []
        self._selected_idx: Optional[int] = None
        self._current_sort: str = "downloads"

        # Picker mode state
        self._mode: str = "browse"
        self._selected_repo: Optional[str] = None
        self._file_results: list[dict] = []
        self._selected_file: Optional[str] = None

        # Widget references (set in compose)
        self._title_widget: Optional[Static] = None
        self._status_widget: Optional[Static] = None
        self._browse_pane: Optional[Container] = None
        self._picker_pane: Optional[Container] = None
        self._browser_table: Optional[DataTable] = None
        self._file_table: Optional[DataTable] = None
        self._sort_select: Optional[Select] = None
        self._search_input: Optional[Input] = None
        self._browse_buttons: Optional[Horizontal] = None
        self._picker_buttons: Optional[Horizontal] = None
        self._select_file_btn: Optional[Button] = None
        self._download_btn: Optional[Button] = None

    # ------------------------------------------------------------------
    # Compose / mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container():
            self._title_widget = Static(
                "📦 BROWSE MODELS  (Hugging Face · GGUF)", classes="title"
            )
            yield self._title_widget

            # ── BROWSE pane ────────────────────────────────────────────
            with Container(id="browse_pane") as self._browse_pane:
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

                self._browser_table = DataTable(id="browser_table")
                self._browser_table.add_columns("Model", "Downloads", "Stars", "Created")
                self._browser_table.cursor_type = "row"
                self._browser_table.zebra_stripes = True
                yield self._browser_table

            # ── PICKER pane (hidden until user picks a repo) ───────────
            with Container(id="picker_pane") as self._picker_pane:
                yield Static("", id="picker_header", classes="picker-header")
                self._file_table = DataTable(id="file_table")
                self._file_table.add_columns("Filename", "Size")
                self._file_table.cursor_type = "row"
                self._file_table.zebra_stripes = True
                yield self._file_table

            # ── Shared status line ─────────────────────────────────────
            self._status_widget = Static("Loading…", classes="status")
            yield self._status_widget

            # ── Browse mode buttons ────────────────────────────────────
            with Horizontal(classes="buttons", id="browse_buttons") as self._browse_buttons:
                self._select_file_btn = Button(
                    "⬇ Select File", id="select_file_btn", variant="success", disabled=True
                )
                yield self._select_file_btn
                yield Button("Close", id="close_btn")

            # ── Picker mode buttons (hidden initially) ─────────────────
            with Horizontal(classes="buttons", id="picker_buttons") as self._picker_buttons:
                self._download_btn = Button(
                    "⬇ Download", id="download_btn", variant="success", disabled=True
                )
                yield self._download_btn
                yield Button("← Back", id="back_btn")

    def on_mount(self) -> None:
        self._picker_pane.display = False
        self._picker_buttons.display = False
        self.run_worker(self._fetch_models("downloads", ""), exclusive=True)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close_btn":
            self.dismiss(None)
        elif bid == "search_btn":
            self._trigger_search()
        elif bid == "select_file_btn":
            self._switch_to_picker()
        elif bid == "download_btn":
            self._start_download()
        elif bid == "back_btn":
            self._switch_to_browse()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_input":
            self._trigger_search()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "sort_select" and event.value:
            self._current_sort = str(event.value)
            search = self._search_input.value.strip() if self._search_input else ""
            self.run_worker(self._fetch_models(self._current_sort, search), exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "browser_table":
            self._selected_idx = event.cursor_row
            if self._select_file_btn:
                self._select_file_btn.disabled = False
        elif event.data_table.id == "file_table":
            row_idx = event.cursor_row
            if 0 <= row_idx < len(self._file_results):
                self._selected_file = self._file_results[row_idx]["name"]
                if self._download_btn:
                    self._download_btn.disabled = False

    def key_escape(self) -> None:
        if self._mode == "picking":
            self._switch_to_browse()
        else:
            self.dismiss(None)

    def key_enter(self) -> None:
        # Enter on a browser row opens file picker; Enter on a file row is handled
        # by on_data_table_row_selected selecting the row — Download requires button click.
        if self._mode == "browse" and self._selected_idx is not None:
            self._switch_to_picker()

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _switch_to_picker(self) -> None:
        if self._selected_idx is None or self._selected_idx >= len(self._results):
            return

        self._selected_repo = self._results[self._selected_idx]["id"]
        self._mode = "picking"
        self._selected_file = None

        # Toggle panes
        self._browse_pane.display = False
        self._browse_buttons.display = False
        self._picker_pane.display = True
        self._picker_buttons.display = True

        # Update title and picker header
        if self._title_widget:
            self._title_widget.update("📦 SELECT FILE")
        try:
            self.query_one("#picker_header", Static).update(
                f"Repository: {self._selected_repo}"
            )
        except Exception:
            pass

        if self._download_btn:
            self._download_btn.disabled = True
        if self._file_table:
            self._file_table.clear()
        if self._status_widget:
            self._status_widget.update("Fetching file list…")

        self.run_worker(self._fetch_file_list(self._selected_repo), exclusive=True)

    def _switch_to_browse(self) -> None:
        self._mode = "browse"
        self._browse_pane.display = True
        self._browse_buttons.display = True
        self._picker_pane.display = False
        self._picker_buttons.display = False

        if self._title_widget:
            self._title_widget.update("📦 BROWSE MODELS  (Hugging Face · GGUF)")
        count = len(self._results)
        if self._status_widget:
            label = f"Showing {count} GGUF models from Hugging Face"
            search = self._search_input.value.strip() if self._search_input else ""
            if search:
                label += f" matching '{search}'"
            self._status_widget.update(label)

    # ------------------------------------------------------------------
    # Download initiation
    # ------------------------------------------------------------------

    def _start_download(self) -> None:
        if not self._selected_repo or not self._selected_file:
            return

        # Guard against concurrent downloads
        existing = self._store.download_progress.value
        if existing and existing.is_running:
            self.app.notify(
                f"Download already in progress: {existing.filename}",
                severity="warning",
            )
            self.dismiss(None)
            return

        from lmstudio_tui.downloader import detect_lmstudio_models_dir, stream_download

        models_dir = detect_lmstudio_models_dir()
        dest_dir = models_dir / self._selected_repo

        # Launch as app-level worker so it survives this modal being dismissed
        self.app.run_worker(
            stream_download(self._selected_repo, self._selected_file, dest_dir, self._store),
            name="hf_downloader",
            exclusive=True,
        )
        self.app.notify(f"⬇ Downloading {self._selected_file}…")
        self.dismiss(self._selected_repo)

    # ------------------------------------------------------------------
    # Browse helpers
    # ------------------------------------------------------------------

    def _trigger_search(self) -> None:
        search = self._search_input.value.strip() if self._search_input else ""
        self.run_worker(self._fetch_models(self._current_sort, search), exclusive=True)

    async def _fetch_models(self, sort: str, search: str) -> None:
        if self._status_widget:
            self._status_widget.update("Loading…")
        if self._select_file_btn:
            self._select_file_btn.disabled = True
        self._selected_idx = None

        api_sort, api_handles = HF_SORT_MAP.get(sort, ("downloads", True))
        params = {
            "filter": "gguf",
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
            logger.error("HF API error: %s", e)
            if self._status_widget:
                self._status_widget.update(f"Failed to load catalog: {e}")
            return

        if sort == "_size":
            data.sort(key=lambda m: _extract_param_billions(m.get("id", "")), reverse=True)

        self._results = data
        self._populate_browser_table(data)

        label = f"Showing {len(data)} GGUF models from Hugging Face"
        if search:
            label += f" matching '{search}'"
        if self._status_widget:
            self._status_widget.update(label)

    def _populate_browser_table(self, models: list[dict]) -> None:
        if not self._browser_table:
            return
        self._browser_table.clear()
        for m in models:
            model_id = m.get("id", "")
            downloads = _fmt_count(m.get("downloads", 0))
            likes = _fmt_count(m.get("likes", 0))
            created = m.get("createdAt", "")[:10]
            display_id = model_id if len(model_id) <= 52 else model_id[:49] + "…"
            self._browser_table.add_row(display_id, downloads, likes, created)

    # ------------------------------------------------------------------
    # Picker helpers
    # ------------------------------------------------------------------

    async def _fetch_file_list(self, repo_id: str) -> None:
        from lmstudio_tui.downloader import fetch_gguf_files
        try:
            files = await fetch_gguf_files(repo_id)
            self._file_results = files
            self._populate_file_table(files)
            if self._status_widget:
                self._status_widget.update(
                    f"{len(files)} quantization variants — select one to download"
                )
        except Exception as e:
            logger.error("Failed to fetch file list for %s: %s", repo_id, e)
            self._file_results = []
            if self._status_widget:
                self._status_widget.update(f"Failed to load file list: {e}")

    def _populate_file_table(self, files: list[dict]) -> None:
        if not self._file_table:
            return
        self._file_table.clear()
        for f in files:
            self._file_table.add_row(f["name"], _fmt_size(f["size"]))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
