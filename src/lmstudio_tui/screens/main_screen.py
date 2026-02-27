"""Main screen for LM Studio TUI."""

from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from lmstudio_tui import __version__

from lmstudio_tui.widgets.ascii_logo import AsciiLogo
from lmstudio_tui.widgets.gpu_panel import GPUPanel
from lmstudio_tui.widgets.models_panel import ModelsPanel
from lmstudio_tui.widgets.chat_panel import ChatPanel


class MainScreen(Screen):
    """Main dashboard screen with GPU, Models, and Chat panels."""

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
    #left-column {
        width: 40%;
        height: 100%;
        layout: vertical;
    }
    #gpu-panel {
        width: 100%;
        height: 60%;
    }
    #chat-panel {
        width: 100%;
        height: 40%;
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
                Vertical(
                    GPUPanel(id="gpu-panel"),
                    ChatPanel(id="chat-panel"),
                    id="left-column"
                ),
                ModelsPanel(id="models-panel"),
                id="content-row"
            ),
            id="main-content"
        )
        yield Footer()
        yield Static(f"v{__version__} | LT-UAT-2024-02-24", id="version-footer")
