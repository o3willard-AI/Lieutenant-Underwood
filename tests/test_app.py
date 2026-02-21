"""Tests for the application."""

import pytest
from textual.app import App

from lmstudio_tui.app import LMStudioApp, main
from lmstudio_tui.screens.main_screen import MainScreen


def test_app_imports():
    """Test that app imports without error."""
    assert LMStudioApp is not None
    assert callable(LMStudioApp)


def test_app_is_app_instance():
    """Test that LMStudioApp is an App."""
    app = LMStudioApp()
    assert isinstance(app, App)


def test_main_screen_imports():
    """Test that main screen imports without error."""
    assert MainScreen is not None
    assert callable(MainScreen)


def test_main_screen_is_screen():
    """Test that MainScreen is a Screen."""
    from textual.screen import Screen

    screen = MainScreen()
    assert isinstance(screen, Screen)


def test_app_bindings():
    """Test that app has expected bindings."""
    app = LMStudioApp()
    # BINDINGS is a list of tuples: (key, action, description)
    bindings_dict = {b[0]: b[1] for b in app.BINDINGS}
    assert "q" in bindings_dict
    assert bindings_dict["q"] == "quit"
    assert "r" in bindings_dict
    assert bindings_dict["r"] == "refresh"
    assert "?" in bindings_dict
    assert bindings_dict["?"] == "help"
