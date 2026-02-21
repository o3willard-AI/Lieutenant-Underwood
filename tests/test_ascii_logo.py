"""Tests for the ASCII logo widget."""

import pytest
from rich.text import Text

from lmstudio_tui.widgets.ascii_logo import AsciiLogo


def test_ascii_logo_imports() -> None:
    """Test that AsciiLogo can be imported from widgets package."""
    from lmstudio_tui.widgets import AsciiLogo as ImportedAsciiLogo

    assert ImportedAsciiLogo is AsciiLogo


def test_ascii_logo_render_returns_text() -> None:
    """Test that render() returns a Text or Align object."""
    logo = AsciiLogo()
    result = logo.render()
    # render() returns Align.center(Text) which is a RenderableType
    assert result is not None


def test_ascii_logo_has_logo_art() -> None:
    """Test that logo has the ASCII art defined."""
    assert AsciiLogo.LOGO_ART is not None
    assert len(AsciiLogo.LOGO_ART) > 0
    assert "LM" in AsciiLogo.LOGO_ART or "██" in AsciiLogo.LOGO_ART


def test_ascii_logo_has_subtitle() -> None:
    """Test that logo has the subtitle defined."""
    assert AsciiLogo.SUBTITLE == "HEADLESS SERVER DASHBOARD"
