"""Main Textual application for LM Studio TUI."""

from textual.app import App

from lmstudio_tui.screens.main_screen import MainScreen


class LMStudioApp(App):
    """LM Studio TUI Application."""

    CSS_PATH = None  # Will add later
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("?", "help", "Help"),
    ]

    def on_mount(self) -> None:
        """App startup."""
        self.push_screen(MainScreen())

    def action_refresh(self) -> None:
        """Refresh all data."""
        pass

    def action_help(self) -> None:
        """Show help."""
        self.notify("Help: Press q to quit, r to refresh")


def main():
    """Entry point for the application."""
    app = LMStudioApp()
    app.run()


if __name__ == "__main__":
    main()
