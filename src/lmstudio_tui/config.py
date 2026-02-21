"""TOML configuration management for LM Studio TUI."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tomli
import tomli_w


@dataclass
class ServerConfig:
    """Server connection configuration."""

    host: str = "localhost"
    port: int = 1234
    timeout: float = 10.0
    retry: bool = True
    api_token_path: Optional[str] = "~/.lmstudio/token"
    verify_ssl: bool = True


@dataclass
class AlertThresholds:
    """GPU alert thresholds."""

    temp_warning: int = 80
    temp_critical: int = 90
    vram_warning: int = 95
    vram_critical: int = 98


@dataclass
class GPUConfig:
    """GPU monitoring configuration."""

    monitoring_enabled: bool = True
    update_frequency: float = 1.0
    alert_thresholds: AlertThresholds = field(default_factory=AlertThresholds)


@dataclass
class AppConfig:
    """Root configuration container."""

    server: ServerConfig = field(default_factory=ServerConfig)
    gpu: GPUConfig = field(default_factory=GPUConfig)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """Load configuration from TOML file.

        Args:
            path: Path to TOML config file. If None or file doesn't exist,
                  returns default configuration.

        Returns:
            AppConfig instance loaded from file or defaults.
        """
        if path is None:
            return cls()

        path = Path(path)
        if not path.exists():
            return cls()

        try:
            with open(path, "rb") as f:
                data = tomli.load(f)
        except (OSError, tomli.TOMLDecodeError):
            return cls()

        # Parse server config
        server_data = data.get("server", {})
        server = ServerConfig(
            host=server_data.get("host", "localhost"),
            port=server_data.get("port", 1234),
            timeout=server_data.get("timeout", 10.0),
            retry=server_data.get("retry", True),
            api_token_path=server_data.get("api_token_path", "~/.lmstudio/token"),
            verify_ssl=server_data.get("verify_ssl", True),
        )

        # Parse GPU config
        gpu_data = data.get("gpu", {})
        alerts_data = data.get("alerts", {})
        temp_data = alerts_data.get("temperature", {})
        vram_data = alerts_data.get("vram", {})

        alert_thresholds = AlertThresholds(
            temp_warning=temp_data.get("warning", 80),
            temp_critical=temp_data.get("critical", 90),
            vram_warning=vram_data.get("warning", 95),
            vram_critical=vram_data.get("critical", 98),
        )

        gpu = GPUConfig(
            monitoring_enabled=gpu_data.get("monitoring_enabled", True),
            update_frequency=gpu_data.get("update_frequency", 1.0),
            alert_thresholds=alert_thresholds,
        )

        return cls(server=server, gpu=gpu)

    def save(self, path: Path) -> None:
        """Save configuration to TOML file.

        Args:
            path: Path where to save the config file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "timeout": self.server.timeout,
                "retry": self.server.retry,
                "api_token_path": self.server.api_token_path,
                "verify_ssl": self.server.verify_ssl,
            },
            "gpu": {
                "monitoring_enabled": self.gpu.monitoring_enabled,
                "update_frequency": self.gpu.update_frequency,
            },
            "alerts": {
                "temperature": {
                    "warning": self.gpu.alert_thresholds.temp_warning,
                    "critical": self.gpu.alert_thresholds.temp_critical,
                },
                "vram": {
                    "warning": self.gpu.alert_thresholds.vram_warning,
                    "critical": self.gpu.alert_thresholds.vram_critical,
                },
            },
        }

        with open(path, "wb") as f:
            tomli_w.dump(data, f)
