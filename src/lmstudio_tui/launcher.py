#!/usr/bin/env python3
"""
Lieutenant-Underwood Launcher

Handles pre-flight checks, LM Studio detection, auto-start, and TUI launch.
This is the entry point for the 'lmstui' command after installation.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# TOML support with fallback
try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Python 3.10
    except ImportError:
        tomllib = None


# Default configuration
DEFAULT_CONFIG = {
    "lmstudio": {
        "host": "localhost",
        "port": None,  # Auto-detect
    },
    "ui": {
        "refresh_rate": 1.0,
    },
    "logging": {
        "level": "INFO",
    },
}

LM_STUDIO_PORTS = [1234, 1235, 1236, 1237, 1238, 1239, 1240]


class Colors:
    """Terminal colors."""
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    NC = "\033[0m"


def print_error(msg: str) -> None:
    print(f"{Colors.RED}✗ {msg}{Colors.NC}", file=sys.stderr)


def print_success(msg: str) -> None:
    print(f"{Colors.GREEN}✓ {msg}{Colors.NC}")


def print_info(msg: str) -> None:
    print(f"{Colors.BLUE}ℹ {msg}{Colors.NC}")


def print_warning(msg: str) -> None:
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.NC}")


def check_python_version() -> bool:
    """Check if Python version is 3.10 or higher."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print_error(f"Python {version.major}.{version.minor} is installed, but 3.10+ is required")
        print_info("Please install Python 3.10 or higher")
        return False
    return True


def find_lm_studio_installation() -> Optional[Path]:
    """Find LM Studio installation."""
    possible_paths = [
        Path.home() / ".lmstudio",
        Path("/opt/lmstudio"),
        Path("/usr/share/lmstudio"),
    ]
    
    desktop_file = Path.home() / ".local" / "share" / "applications" / "lmstudio.desktop"
    if desktop_file.exists():
        return desktop_file
    
    system_desktop = Path("/usr/share/applications/lmstudio.desktop")
    if system_desktop.exists():
        return system_desktop
    
    for path in possible_paths:
        if path.exists():
            return path
    
    return None


def check_lm_studio_installed() -> bool:
    """Check if LM Studio is installed."""
    install_path = find_lm_studio_installation()
    
    try:
        result = subprocess.run(
            ["which", "lmstudio"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass
    
    return install_path is not None


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def find_lm_studio_port(host: str = "localhost") -> Optional[int]:
    """Find which port LM Studio is running on."""
    for port in LM_STUDIO_PORTS:
        if is_port_open(host, port):
            try:
                import urllib.request
                req = urllib.request.Request(
                    f"http://{host}:{port}/v1/models",
                    headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=2) as response:
                    if response.status == 200:
                        return port
            except Exception:
                continue
    return None


def is_lm_studio_running(host: str = "localhost") -> tuple[bool, Optional[int]]:
    """Check if LM Studio is running and return status and port."""
    port = find_lm_studio_port(host)
    if port:
        return True, port
    return False, None


def start_lm_studio() -> bool:
    """Attempt to start LM Studio."""
    print_info("Attempting to start LM Studio...")
    
    try:
        result = subprocess.run(
            ["lmstudio", "--headless"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0 or "already running" in result.stderr.lower():
            print_success("LM Studio started")
            return True
    except FileNotFoundError:
        pass
    except Exception as e:
        print_warning(f"Could not start via command: {e}")
    
    running, port = is_lm_studio_running()
    if running:
        print_success(f"LM Studio is already running on port {port}")
        return True
    
    return False


def prompt_start_lm_studio() -> tuple[bool, Optional[int]]:
    """Prompt user to start LM Studio."""
    print_warning("LM Studio is installed but not running")
    print()
    
    while True:
        try:
            response = input("Would you like to start LM Studio? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print_error("Cancelled by user")
            return False, None
        
        if response in ("", "y", "yes"):
            if start_lm_studio():
                print_info("Waiting for LM Studio to start...")
                time.sleep(3)
                
                running, port = is_lm_studio_running()
                if running:
                    return True, port
                else:
                    print_error("LM Studio did not start properly")
                    return False, None
            else:
                print_error("Failed to start LM Studio")
                return False, None
        elif response in ("n", "no"):
            print_info("Please start LM Studio manually and try again")
            return False, None
        else:
            print("Please enter 'y' or 'n'")


def load_config() -> dict:
    """Load user configuration."""
    config = DEFAULT_CONFIG.copy()
    
    config_paths = [
        Path.home() / ".config" / "lmstui" / "config.toml",
        Path.home() / ".lmstui" / "config.toml",
    ]
    
    for config_path in config_paths:
        if config_path.exists() and tomllib:
            try:
                with open(config_path, "rb") as f:
                    user_config = tomllib.load(f)
                    for section, values in user_config.items():
                        if section in config and isinstance(values, dict):
                            config[section].update(values)
                        else:
                            config[section] = values
                break
            except Exception as e:
                print_warning(f"Could not load config from {config_path}: {e}")
    
    return config


def save_default_config() -> None:
    """Create default configuration file."""
    config_dir = Path.home() / ".config" / "lmstui"
    config_file = config_dir / "config.toml"
    
    if config_file.exists():
        return
    
    config_dir.mkdir(parents=True, exist_ok=True)
    
    default_toml = '''# Lieutenant-Underwood Configuration

[lmstudio]
host = "localhost"
# port = 1234  # Auto-detect if commented

[ui]
refresh_rate = 1.0

[logging]
level = "INFO"
'''
    
    try:
        with open(config_file, "w") as f:
            f.write(default_toml)
        print_success(f"Created default config at {config_file}")
    except Exception as e:
        print_warning(f"Could not create config file: {e}")


def launch_tui(host: str, port: int, args: argparse.Namespace) -> int:
    """Launch the TUI application."""
    try:
        from lmstudio_tui.app import LMStudioApp
    except ImportError:
        print_error("Could not import LMStudioApp")
        print_info("Make sure Lieutenant-Underwood is properly installed")
        return 1
    
    os.environ["LMSTUDIO_HOST"] = host
    os.environ["LMSTUDIO_PORT"] = str(port)
    
    if args.debug:
        os.environ["LMSTUDIO_DEBUG"] = "1"
    
    try:
        app = LMStudioApp()
        app.run()
        return 0
    except Exception as e:
        print_error(f"Failed to launch TUI: {e}")
        return 1


def main() -> int:
    """Main launcher entry point."""
    parser = argparse.ArgumentParser(
        description="Lieutenant-Underwood - LM Studio Terminal User Interface",
        prog="lmstui"
    )
    parser.add_argument("--host", default=None, help="LM Studio host")
    parser.add_argument("--port", type=int, default=None, help="LM Studio port")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--version", action="version", version="%(prog)s 0.2.0")
    
    args = parser.parse_args()
    
    print()
    print(f"{Colors.BLUE}╔════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║{Colors.NC}        Lieutenant-Underwood v0.2.0                    {Colors.BLUE}║{Colors.NC}")
    print(f"{Colors.BLUE}║{Colors.NC}           LM Studio Terminal User Interface            {Colors.BLUE}║{Colors.NC}")
    print(f"{Colors.BLUE}╚════════════════════════════════════════════════════════╝{Colors.NC}")
    print()
    
    print_info("Checking Python version...")
    if not check_python_version():
        return 1
    print_success(f"Python {sys.version_info.major}.{sys.version_info.minor} OK")
    print()
    
    print_info("Checking LM Studio installation...")
    if not check_lm_studio_installed():
        print_error("LM Studio is not installed")
        print()
        print("Please install LM Studio first:")
        print("  https://lmstudio.ai/")
        print()
        return 1
    print_success("LM Studio is installed")
    print()
    
    config = load_config()
    save_default_config()
    
    host = args.host or config["lmstudio"]["host"]
    
    print_info(f"Checking if LM Studio is running on {host}...")
    running, detected_port = is_lm_studio_running(host)
    
    if not running:
        success, detected_port = prompt_start_lm_studio()
        if not success:
            print()
            print_error("Cannot proceed without LM Studio running")
            print()
            print("To start LM Studio manually:")
            print("  1. Open LM Studio desktop app, or")
            print("  2. Run: lmstudio --headless")
            print()
            return 1
    
    port = args.port or config["lmstudio"]["port"] or detected_port
    
    if not port:
        print_error("Could not determine LM Studio port")
        print_info("Please specify with --port")
        return 1
    
    print_success(f"LM Studio detected at {host}:{port}")
    print()
    
    print_info("Launching Lieutenant-Underwood...")
    print()
    
    return launch_tui(host, port, args)


if __name__ == "__main__":
    sys.exit(main())
