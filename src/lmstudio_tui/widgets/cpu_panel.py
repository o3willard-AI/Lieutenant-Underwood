"""CPU and RAM status panel for LM Studio TUI."""

from __future__ import annotations

from typing import Optional

from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import DataTable, Static

from lmstudio_tui.cpu.monitor import CPUMetrics
from lmstudio_tui.store import get_store


class CPUPanel(Container):
    """Read-only panel showing CPU model, free RAM, LM Studio RAM, CPU util, and LMS CPU %.

    Mirrors the GPUPanel pattern: watches store.cpu_metrics and renders a DataTable.
    """

    DEFAULT_CSS = """
    CPUPanel {
        width: 100%;
        height: auto;
        padding: 1;
    }
    CPUPanel Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        content-align: left middle;
    }
    CPUPanel DataTable {
        width: 100%;
        height: auto;
        border: solid $primary;
    }
    CPUPanel DataTable > .datatable--header {
        text-style: bold;
        color: $primary;
    }
    CPUPanel Static.error {
        color: $error;
        text-style: bold;
        content-align: center middle;
    }
    CPUPanel Static.no-cpu {
        color: $text-muted;
        content-align: center middle;
    }
    """

    _cpu_metrics: reactive[Optional[CPUMetrics]] = reactive(None)
    _cpu_error: reactive[Optional[str]] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._store = get_store()
        self._data_table: Optional[DataTable] = None

    def compose(self):
        yield Static("💻 CPU STATUS", classes="title")
        self._data_table = DataTable(show_header=True, header_height=1, cursor_type="none")
        yield self._data_table

    def on_mount(self) -> None:
        self._unwatch_metrics = self._store.cpu_metrics.watch(self._on_metrics_change)
        self._unwatch_error = self._store.cpu_error.watch(self._on_error_change)

        if self._data_table:
            self._setup_columns()

        initial = self._store.cpu_metrics.value
        if initial:
            self._cpu_metrics = initial

        initial_err = self._store.cpu_error.value
        if initial_err:
            self._cpu_error = initial_err

    def on_unmount(self) -> None:
        if hasattr(self, "_unwatch_metrics"):
            self._unwatch_metrics()
        if hasattr(self, "_unwatch_error"):
            self._unwatch_error()

    def _setup_columns(self) -> None:
        if not self._data_table:
            return
        self._data_table.add_column("CPU Model", width=28)
        self._data_table.add_column("Free RAM", width=10)
        self._data_table.add_column("LMS RAM", width=10)
        self._data_table.add_column("CPU Util", width=10)
        self._data_table.add_column("LMS CPU", width=10)

    def _on_metrics_change(self, old: Optional[CPUMetrics], new: Optional[CPUMetrics]) -> None:
        self._cpu_metrics = new

    def _on_error_change(self, old: Optional[str], new: Optional[str]) -> None:
        self._cpu_error = new

    def watch__cpu_metrics(self, metrics: Optional[CPUMetrics]) -> None:
        if self._data_table is None:
            self._restore_data_table()
        self._update_data_table(metrics)

    def watch__cpu_error(self, error: Optional[str]) -> None:
        if error:
            self._show_error(error)

    def _update_data_table(self, metrics: Optional[CPUMetrics]) -> None:
        if not self._data_table:
            return
        self._data_table.clear()
        if metrics is None:
            self._data_table.add_row("Waiting…", "—", "—", "—", "—")
            return

        # Truncate CPU model to fit column
        cpu_model = metrics.cpu_model
        if len(cpu_model) > 27:
            cpu_model = cpu_model[:24] + "…"

        self._data_table.add_row(
            cpu_model,
            f"{metrics.ram_free_gb:.1f} GB",
            f"{metrics.ram_lmstudio_gb:.1f} GB",
            f"{metrics.cpu_utilization:.1f}%",
            f"{metrics.cpu_lmstudio_pct:.1f}%",
        )

    def _restore_data_table(self) -> None:
        self.remove_children()
        self._data_table = DataTable(show_header=True, header_height=1, cursor_type="none")
        self.mount(Static("💻 CPU STATUS", classes="title"))
        self.mount(self._data_table)
        self._setup_columns()

    def _show_error(self, error: str) -> None:
        self.remove_children()
        self._data_table = None
        self.mount(Static(f"CPU Error: {error}", classes="error"))
