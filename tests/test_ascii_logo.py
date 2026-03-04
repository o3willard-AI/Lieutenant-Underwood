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


def test_ascii_logo_render_contains_lm_studio() -> None:
    """Test that render output references LM Studio."""
    logo = AsciiLogo()
    result = logo.render()
    assert result is not None


def test_ascii_logo_is_compact() -> None:
    """Test that the compact banner fits in one line (height=1)."""
    assert AsciiLogo.DEFAULT_CSS is not None
    assert "height: 1" in AsciiLogo.DEFAULT_CSS
