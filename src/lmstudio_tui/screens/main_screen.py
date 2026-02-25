"""Main screen for LM Studio TUI."""

from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from lmstudio_tui import __version__

from lmstudio_tui.widgets.ascii_logo import AsciiLogo
from lmstudio_tui.widgets.gpu_panel import GPUPanel
from lmstudio_tui.widgets.models_panel import ModelsPanel


class MainScreen(Screen):
    """Main dashboard screen with GPU and Models panels."""

    DEFAULT_CSS = """
    MainScreen {
        layout: vertical;
    }
    #logo-container {
        height: auto;
        content-align: center middle;
    }
    #content-row {
        width: 100%;
        height: 1fr;
    }
    #gpu-panel {
        width: 40%;
        height: 100%;
    }
    #models-panel {
        width: 60%;
        height: 100%;
    }
    #version-footer {
        height: 1;
        width: 100%;
        content-align: right middle;
        color: $text-muted;
    }
    """

    def compose(self):
        """Compose the main layout."""
        yield Vertical(
            Container(AsciiLogo(), id="logo-container"),
            Horizontal(
                GPUPanel(id="gpu-panel"),
                ModelsPanel(id="models-panel"),
                id="content-row"
            ),
            id="main-content"
        )
        yield Footer()
        yield Static(f"v{__version__} | LT-UAT-2024-02-24", id="version-footer")
