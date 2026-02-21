"""Main screen for LM Studio TUI."""

from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Label


class MainScreen(Screen):
    """Main dashboard screen."""

    def compose(self):
        """Compose the main layout."""
        yield Container(Label("LM Studio TUI - Press 'q' to quit"), id="placeholder")
        yield Footer()
