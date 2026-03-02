"""GPU panel widgets for LM Studio TUI."""

from __future__ import annotations

from rich.text import Text
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import DataTable, Static

from lmstudio_tui.gpu.monitor import GPUMetrics
from lmstudio_tui.store import get_store


class VRAMBar(Static):
    """VRAM usage bar with color coding.
    
    Color logic:
    - Green (<80%)
    - Yellow (80-95%)
    - Red (>95%)
    """

    DEFAULT_CSS = """
    VRAMBar {
        height: 1;
        content-align: center middle;
    }
    VRAMBar.green {
        color: $success;
        background: $success 0%;
    }
    VRAMBar.yellow {
        color: $warning;
        background: $warning 0%;
    }
    VRAMBar.red {
        color: $error;
        background: $error 0%;
    }
    """

    def __init__(self, vram_used: int = 0, vram_total: int = 1, **kwargs):
        """Initialize VRAM bar with usage values.
        
        Args:
            vram_used: Used VRAM in MB.
            vram_total: Total VRAM in MB.
            **kwargs: Additional arguments passed to Static.
        """
        self._vram_used = vram_used
        self._vram_total = max(vram_total, 1)
        super().__init__(**kwargs)
        self._update_display()

    @property
    def total(self) -> int:
        """Get total VRAM (for API compatibility with ProgressBar)."""
        return self._vram_total

    @property
    def progress(self) -> int:
        """Get used VRAM (for API compatibility with ProgressBar)."""
        return self._vram_used

    def _update_vram(self, vram_used: int) -> None:
        """Update the VRAM bar with new usage.
        
        Args:
            vram_used: Used VRAM in MB.
        """
        self._vram_used = vram_used
        self._update_display()

    def _update_display(self) -> None:
        """Update display text and color."""
        percentage = (self._vram_used / self._vram_total) * 100
        self.update(f"{percentage:.1f}%")
        self._update_style()

    def _update_style(self) -> None:
        """Update bar color based on usage percentage."""
        percentage = (self._vram_used / self._vram_total) * 100

        # Apply color classes based on percentage
        self.remove_class("green", "yellow", "red")
        if percentage < 80:
            self.add_class("green")
        elif percentage <= 95:
            self.add_class("yellow")
        else:
            self.add_class("red")

    def render(self) -> Text:
        """Render the VRAM bar with percentage label."""
        percentage = (self._vram_used / self._vram_total) * 100
        return Text(f"{percentage:.1f}%", justify="center")


class TempDisplay(Static):
    """Temperature display with color coding.
    
    Color logic:
    - Green (<80°C)
    - Yellow (80-90°C)
    - Red (>90°C)
    """

    DEFAULT_CSS = """
    TempDisplay {
        width: auto;
        content-align: center middle;
    }
    TempDisplay.green {
        color: $success;
    }
    TempDisplay.yellow {
        color: $warning;
    }
    TempDisplay.red {
        color: $error;
    }
    """

    def __init__(self, temperature: int = 0, **kwargs):
        """Initialize temperature display.
        
        Args:
            temperature: GPU temperature in Celsius.
            **kwargs: Additional arguments passed to Static.
        """
        super().__init__(f"{temperature}°C", **kwargs)
        self._update_style(temperature)

    def update_temperature(self, temperature: int) -> None:
        """Update temperature display with new value.
        
        Args:
            temperature: GPU temperature in Celsius.
        """
        self.update(f"{temperature}°C")
        self._update_style(temperature)

    def _update_style(self, temperature: int) -> None:
        """Update color class based on temperature.
        
        Args:
            temperature: GPU temperature in Celsius.
        """
        self.remove_class("green", "yellow", "red")
        if temperature < 80:
            self.add_class("green")
        elif temperature <= 90:
            self.add_class("yellow")
        else:
            self.add_class("red")



class GPUPanel(Container):
    """Container with reactive binding to store.

    Watches gpu_metrics from the store and renders GPU info in a DataTable.
    Shows error message if gpu_error is set.
    """

    DEFAULT_CSS = """
    GPUPanel {
        width: 100%;
        height: auto;
        padding: 1;
    }
    GPUPanel Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
        content-align: left middle;
    }
    GPUPanel DataTable {
        width: 100%;
        height: auto;
        border: solid $primary;
    }
    GPUPanel DataTable > .datatable--header {
        text-style: bold;
        color: $primary;
    }
    GPUPanel Static.error {
        color: $error;
        text-style: bold;
        content-align: center middle;
    }
    GPUPanel Static.no-gpu {
        color: $text-muted;
        content-align: center middle;
    }
    """

    # Reactive state tracking
    _gpu_metrics: reactive[list[GPUMetrics]] = reactive(list)
    _gpu_error: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs):
        """Initialize GPU panel with store binding."""
        super().__init__(**kwargs)
        self._store = get_store()
        self._data_table: DataTable | None = None

    def on_mount(self) -> None:
        """Mount panel and set up store watchers."""
        # Watch for GPU metrics changes
        self._unwatch_metrics = self._store.gpu_metrics.watch(
            self._on_metrics_change
        )
        # Watch for GPU errors
        self._unwatch_error = self._store.gpu_error.watch(
            self._on_error_change
        )

        # Initialize DataTable columns BEFORE any data arrives
        # This ensures headers are properly rendered
        if self._data_table:
            self._setup_data_table()
            self._data_table.show_header = True
            # Force a refresh to ensure headers render
            self._data_table.refresh()

        # Initial render if data already available
        initial_metrics = self._store.gpu_metrics.value
        if initial_metrics:
            self._gpu_metrics = initial_metrics

        initial_error = self._store.gpu_error.value
        if initial_error:
            self._gpu_error = initial_error

    def _setup_data_table(self) -> None:
        """Set up DataTable columns."""
        if not self._data_table:
            return

        self._data_table.show_header = True
        self._data_table.header_height = 1
        self._data_table.add_column("GPU", width=25)
        self._data_table.add_column("VRAM Total", width=12)
        self._data_table.add_column("VRAM Used", width=12)
        self._data_table.add_column("Temp", width=8)
        self._data_table.add_column("Util", width=8)

    def on_unmount(self) -> None:
        """Unmount panel and clean up watchers."""
        if hasattr(self, '_unwatch_metrics'):
            self._unwatch_metrics()
        if hasattr(self, '_unwatch_error'):
            self._unwatch_error()

    def _on_metrics_change(self, old: list[GPUMetrics], new: list[GPUMetrics]) -> None:
        """Handle GPU metrics change from store.

        Args:
            old: Previous metrics list.
            new: New metrics list.
        """
        self._gpu_metrics = new

    def _on_error_change(self, old: str | None, new: str | None) -> None:
        """Handle GPU error change from store.

        Args:
            old: Previous error (if any).
            new: New error (if any).
        """
        self._gpu_error = new

    def _restore_data_table(self) -> None:
        """Re-create the DataTable after _show_error() removed it."""
        self.remove_children()
        self._data_table = DataTable(show_header=True, header_height=1)
        self.mount(Static("🎮 GPU STATUS", classes="title"))
        self.mount(self._data_table)
        self._setup_data_table()

    def watch__gpu_metrics(self, metrics: list[GPUMetrics]) -> None:
        """React to metrics change - restore table if needed, then update."""
        if self._data_table is None:
            self._restore_data_table()
        self._update_data_table(metrics)

    def watch__gpu_error(self, error: str | None) -> None:
        """React to error change - show error message."""
        if error:
            self._show_error(error)

    def _update_data_table(self, metrics: list[GPUMetrics]) -> None:
        """Update DataTable with GPU metrics.

        Args:
            metrics: List of GPUMetrics to display.
        """
        if not self._data_table:
            return

        # Clear existing rows
        self._data_table.clear()

        if not metrics:
            # No GPUs detected - add a message row
            self._data_table.add_row("No GPUs detected", "", "", "", "")
            return

        # Add GPU data rows
        for metric in metrics:
            vram_total_gb = metric.vram_total / 1024
            vram_used_gb = metric.vram_used / 1024
            self._data_table.add_row(
                metric.name,
                f"{vram_total_gb:.1f} GB",
                f"{vram_used_gb:.1f} GB",
                f"{metric.temperature}°C",
                f"{metric.utilization}%"
            )

    def _show_error(self, error: str) -> None:
        """Display error message.

        Args:
            error: Error message to display.
        """
        self.remove_children()
        self._data_table = None
        self.mount(Static(f"GPU Error: {error}", classes="error"))

    def compose(self):
        """Compose initial content."""
        # Title
        yield Static("🎮 GPU STATUS", classes="title")
        # DataTable for GPU info with header row
        self._data_table = DataTable(show_header=True, header_height=1)
        yield self._data_table
