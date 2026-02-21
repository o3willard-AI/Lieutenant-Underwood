"""Main screen for LM Studio TUI."""

from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Footer

from lmstudio_tui.widgets.ascii_logo import AsciiLogo
from lmstudio_tui.widgets.gpu_panel import GPUPanel


class MainScreen(Screen):
    """Main dashboard screen."""

    def compose(self):
        """Compose the main layout."""
        yield Vertical(
            Container(AsciiLogo(), id="logo-container"),
            GPUPanel(id="gpu-panel"),
            id="main-content"
        )
        yield Footer()
