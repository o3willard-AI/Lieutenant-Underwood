"""Main screen for LM Studio TUI."""

import datetime

from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Static

from lmstudio_tui import __version__

from lmstudio_tui.widgets.ascii_logo import AsciiLogo
from lmstudio_tui.widgets.cpu_panel import CPUPanel
from lmstudio_tui.widgets.gpu_panel import GPUPanel
from lmstudio_tui.widgets.models_panel import ModelsPanel
from lmstudio_tui.widgets.chat_panel import ChatPanel


class MainScreen(Screen):
    """Main dashboard screen."""

    DEFAULT_CSS = """
    MainScreen {
        layout: vertical;
    }
    #logo-container {
        height: auto;
        content-align: center middle;
    }
    #content-column {
        width: 100%;
        height: 1fr;
        layout: vertical;
    }
    #gpu-panel {
        width: 100%;
        height: auto;
    }
    #cpu-panel {
        width: 100%;
        height: auto;
    }
    #models-panel {
        width: 100%;
        height: auto;
    }
    #chat-panel {
        width: 100%;
        height: 1fr;
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
            AsciiLogo(id="logo-container"),
            Vertical(
                GPUPanel(id="gpu-panel"),
                CPUPanel(id="cpu-panel"),
                ModelsPanel(id="models-panel"),
                ChatPanel(id="chat-panel"),
                id="content-column",
            ),
            id="main-content",
        )
        yield Footer()
        yield Static(f"v{__version__} | {datetime.date.today().isoformat()}", id="version-footer")
