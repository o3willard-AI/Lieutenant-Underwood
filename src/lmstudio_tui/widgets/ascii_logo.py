"""Compact header banner for LM Studio TUI."""

from rich.align import Align
from rich.text import Text
from textual.widgets import Static


class AsciiLogo(Static):
    """Compact single-line header banner."""

    DEFAULT_CSS = """
    AsciiLogo {
        height: 1;
        content-align: center middle;
    }
    """

    def render(self) -> Text:
        """Render a compact centered header."""
        text = Text()
        text.append("LM ", style="bold blue")
        text.append("STUDIO", style="bold magenta")
        text.append("  TUI", style="bold blue")
        text.append("  ·  Headless Server Dashboard", style="dim")
        return Align.center(text)
