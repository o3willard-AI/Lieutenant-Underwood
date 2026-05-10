"""LM Studio TUI - Terminal UI for LM Studio headless server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lmstudio-tui")
except PackageNotFoundError:
    __version__ = "unknown"
