"""Model deletion screen for LM Studio TUI.

Scans ~/.lmstudio/models for model directories, shows them with size,
and lets the user delete one with a two-step confirmation.  LM Studio
watches the models directory and removes the entry from its list
automatically within a few seconds of the files being removed.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

from lmstudio_tui.store import get_store
from lmstudio_tui.utils import format_size

logger = logging.getLogger(__name__)

_MODELS_ROOT = Path.home() / ".lmstudio" / "models"


@dataclass
class _ModelEntry:
    publisher: str
    model_dir: str
    path: Path
    total_bytes: int
    file_count: int
    loaded: bool = False


def _scan() -> list[_ModelEntry]:
    entries: list[_ModelEntry] = []
    if not _MODELS_ROOT.exists():
        return entries
    for pub_dir in sorted(_MODELS_ROOT.iterdir()):
        if not pub_dir.is_dir():
            continue
        for mdl_dir in sorted(pub_dir.iterdir()):
            if not mdl_dir.is_dir():
                continue
            files = [f for f in mdl_dir.rglob("*") if f.is_file()]
            entries.append(_ModelEntry(
                publisher=pub_dir.name,
                model_dir=mdl_dir.name,
                path=mdl_dir,
                total_bytes=sum(f.stat().st_size for f in files),
                file_count=len(files),
            ))
    return entries


def _mark_loaded(entries: list[_ModelEntry], loaded_names: list[str]) -> None:
    """Best-effort: flag entries whose dir name matches a loaded model name."""
    for entry in entries:
        dir_norm = entry.model_dir.lower().replace("-", "").replace("_", "")
        for name in loaded_names:
            name_norm = name.lower().replace(" ", "").replace("-", "").replace("_", "")
            if len(name_norm) >= 6 and name_norm[:12] in dir_norm:
                entry.loaded = True
                break


class DeleteModelScreen(ModalScreen):
    """Modal screen for deleting models from disk.

    Navigate with arrow keys.  Press Enter on a model to enter confirm
    mode; press Enter again to delete, or Escape to cancel.
    """

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    DEFAULT_CSS = """
    DeleteModelScreen {
        align: center middle;
    }
    DeleteModelScreen > Container {
        width: 90%;
        max-width: 100;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1;
    }
    DeleteModelScreen Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        margin-bottom: 1;
    }
    DeleteModelScreen DataTable {
        width: 100%;
        height: auto;
        max-height: 20;
    }
    DeleteModelScreen DataTable > .datatable--header {
        text-style: bold;
        background: $surface;
        color: $primary;
    }
    DeleteModelScreen DataTable > .datatable--row-cursor {
        background: $primary-darken-2;
    }
    DeleteModelScreen Static.hint {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }
    DeleteModelScreen Static.confirm-bar {
        height: 1;
        color: $warning;
        text-style: bold;
        margin-top: 1;
    }
    DeleteModelScreen Static.empty {
        height: 3;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._store = get_store()
        self._entries: list[_ModelEntry] = []
        self._table: Optional[DataTable] = None
        self._hint: Optional[Static] = None
        self._confirm_bar: Optional[Static] = None
        self._confirming: bool = False

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("🗑  DELETE MODEL", classes="title")
            self._table = DataTable(id="delete_table")
            self._table.cursor_type = "row"
            self._table.zebra_stripes = True
            yield self._table
            self._hint = Static(
                "[dim]↑↓[/dim] navigate  [dim]Enter[/dim] select for deletion  [dim]Esc[/dim] back",
                classes="hint",
            )
            yield self._hint
            self._confirm_bar = Static("", classes="confirm-bar")
            self._confirm_bar.display = False
            yield self._confirm_bar

    def on_mount(self) -> None:
        self._load_entries()

    def _load_entries(self) -> None:
        entries = _scan()
        loaded_names = [
            m.name for m in self._store.models.value if m.loaded
        ]
        _mark_loaded(entries, loaded_names)
        self._entries = entries

        assert self._table is not None
        self._table.clear(columns=True)

        if not entries:
            self._table.add_columns("Info")
            self._table.add_row("No models found in ~/.lmstudio/models")
            return

        self._table.add_columns("Publisher", "Model", "Size", "Files", "")
        for e in entries:
            status = "[bold red]LOADED[/bold red]" if e.loaded else "[dim]on disk[/dim]"
            self._table.add_row(
                e.publisher,
                e.model_dir,
                format_size(e.total_bytes),
                str(e.file_count),
                status,
            )

    def _selected_entry(self) -> Optional[_ModelEntry]:
        if not self._table or self._table.cursor_row is None:
            return None
        idx = self._table.cursor_row
        if 0 <= idx < len(self._entries):
            return self._entries[idx]
        return None

    def _exit_confirm(self) -> None:
        self._confirming = False
        assert self._confirm_bar is not None
        self._confirm_bar.display = False
        assert self._hint is not None
        self._hint.display = True

    def on_key(self, event) -> None:
        if event.key == "escape":
            if self._confirming:
                self._exit_confirm()
                event.stop()
            # else let the BINDINGS dismiss handler fire
            return

        if event.key == "enter":
            event.stop()
            if not self._confirming:
                # First Enter: enter confirmation mode
                entry = self._selected_entry()
                if entry is None:
                    return
                if entry.loaded:
                    self.app.notify(
                        f"Cannot delete '{entry.model_dir}' — model is currently loaded. "
                        "Unload it first.",
                        severity="error",
                        timeout=5,
                    )
                    return
                self._confirming = True
                assert self._confirm_bar is not None
                self._confirm_bar.update(
                    f"⚠  Delete [bold]{entry.publisher}/{entry.model_dir}[/bold] "
                    f"({format_size(entry.total_bytes)})? "
                    "[bold]Enter[/bold]=confirm  [bold]Esc[/bold]=cancel"
                )
                self._confirm_bar.display = True
                assert self._hint is not None
                self._hint.display = False
            else:
                # Second Enter: actually delete
                entry = self._selected_entry()
                if entry is None:
                    self._exit_confirm()
                    return
                self._delete(entry)

    def _delete(self, entry: _ModelEntry) -> None:
        try:
            shutil.rmtree(entry.path)
            # Remove publisher directory if now empty
            pub_dir = entry.path.parent
            if pub_dir.exists() and not any(pub_dir.iterdir()):
                pub_dir.rmdir()
            logger.info(f"Deleted model: {entry.publisher}/{entry.model_dir}")
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            self.app.notify(f"Delete failed: {e}", severity="error", timeout=6)
            self._exit_confirm()
            return

        freed = format_size(entry.total_bytes)
        self.app.notify(
            f"Deleted {entry.publisher}/{entry.model_dir} ({freed} freed). "
            "LM Studio will update its model list automatically.",
            severity="information",
            timeout=6,
        )
        # Force an immediate model-list refresh so the models panel updates
        self._trigger_refresh()
        self.dismiss()

    def _trigger_refresh(self) -> None:
        """Kick off an async model-list fetch so the panel updates promptly."""
        async def _fetch() -> None:
            try:
                client = self._store.api_client
                if client:
                    models = await client.get_models()
                    self._store.models.value = models
            except Exception:
                pass
        self.app.run_worker(_fetch(), exclusive=False)
