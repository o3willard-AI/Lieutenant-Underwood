"""Main screen for LM Studio TUI."""

from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer

from lmstudio_tui.widgets.ascii_logo import AsciiLogo


class MainScreen(Screen):
    """Main dashboard screen."""

    def compose(self):
        """Compose the main layout."""
        yield Container(AsciiLogo(), id="logo-container")
        yield Footer()
