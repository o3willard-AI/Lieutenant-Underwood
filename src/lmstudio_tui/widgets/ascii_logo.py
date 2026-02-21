"""ASCII Logo widget for LM Studio TUI."""

from rich.align import Align
from rich.text import Text
from textual.widgets import Static


class AsciiLogo(Static):
    """LM Studio ASCII logo with styling."""

    LOGO_ART = """██╗     ███╗   ███╗     ███████╗████████╗██╗   ██╗██████╗ ██╗ ██████╗
██║     ████╗ ████║     ██╔════╝╚══██╔══╝██║   ██║██╔══██╗██║██╔═══██╗
██║     ██╔████╔██║     ███████╗   ██║   ██║   ██║██║  ██║██║██║   ██║
██║     ██║╚██╔╝██║     ╚════██║   ██║   ██║   ██║██║  ██║██║██║   ██║
███████╗██║ ╚═╝ ██║     ███████║   ██║   ╚██████╔╝██████╔╝██║╚██████╔╝
╚══════╝╚═╝     ╚═╝     ╚══════╝   ╚═╝    ╚═════╝ ╚═════╝ ╚═╝ ╚═════╝"""

    SUBTITLE = "HEADLESS SERVER DASHBOARD"

    def render(self) -> Text:
        """Render centered logo with colors."""
        logo_lines = self.LOGO_ART.split("\n")
        colored_lines: list[Text] = []

        for line in logo_lines:
            # First 70 chars: "LM" in bold blue
            # Remaining: "Studio" in bold magenta
            lm_part = line[:70] if len(line) >= 70 else line
            studio_part = line[70:] if len(line) > 70 else ""

            colored_line = Text()
            if lm_part:
                colored_line.append(lm_part, style="bold blue")
            if studio_part:
                colored_line.append(studio_part, style="bold magenta")
            colored_lines.append(colored_line)

        # Add subtitle with dim style
        subtitle = Text(f"\n{self.SUBTITLE}", style="dim")
        colored_lines.append(subtitle)

        # Combine all lines
        logo_text = Text.assemble(*[line + Text("\n") for line in colored_lines])

        # Center the whole thing
        return Align.center(logo_text)
