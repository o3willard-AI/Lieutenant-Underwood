"""TOML configuration management for LM Studio TUI."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dacite
import tomli
import tomli_w

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Server connection configuration."""

    host: str = "localhost"
    port: int = 1234
    timeout: float = 10.0
    retry: bool = True
    api_token_path: Optional[str] = None
    verify_ssl: bool = True

    @property
    def resolved_api_token_path(self) -> Optional[Path]:
        """Return resolved API token path, expanding ~ if set."""
        if self.api_token_path is None:
            return Path.home() / ".lmstudio" / "token"
        return Path(self.api_token_path).expanduser()


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
                raw_data = tomli.load(f)
        except tomli.TOMLDecodeError as e:
            logger.warning(
                "Config file %s has invalid TOML: %s. Using defaults.", path, e
            )
            return cls()
        except OSError as e:
            logger.warning("Cannot read config file %s: %s. Using defaults.", path, e)
            return cls()

        # Transform flat TOML structure to nested dataclass structure
        data: dict = {}

        # Server config (direct mapping)
        if "server" in raw_data:
            data["server"] = raw_data["server"]

        # GPU config with nested alert thresholds
        if "gpu" in raw_data or "alerts" in raw_data:
            data["gpu"] = dict(raw_data.get("gpu", {}))

            # Map alerts.temperature and alerts.vram into alert_thresholds
            # TOML: alerts.temperature.warning -> alert_thresholds.temp_warning
            alerts_data = raw_data.get("alerts", {})
            temp_data = alerts_data.get("temperature", {})
            vram_data = alerts_data.get("vram", {})

            alert_thresholds = {}
            if "warning" in temp_data:
                alert_thresholds["temp_warning"] = temp_data["warning"]
            if "critical" in temp_data:
                alert_thresholds["temp_critical"] = temp_data["critical"]
            if "warning" in vram_data:
                alert_thresholds["vram_warning"] = vram_data["warning"]
            if "critical" in vram_data:
                alert_thresholds["vram_critical"] = vram_data["critical"]

            if alert_thresholds:
                data["gpu"]["alert_thresholds"] = alert_thresholds

        try:
            return dacite.from_dict(
                data_class=cls,
                data=data,
                config=dacite.Config(strict=False),
            )
        except dacite.DaciteError as e:
            logger.warning(
                "Config file %s has invalid structure: %s. Using defaults.", path, e
            )
            return cls()

    def save(self, path: Path) -> None:
        """Save configuration to TOML file.

        Args:
            path: Path where to save the config file.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Only include api_token_path if it's set (not None)
        server_data = {
            "host": self.server.host,
            "port": self.server.port,
            "timeout": self.server.timeout,
            "retry": self.server.retry,
            "verify_ssl": self.server.verify_ssl,
        }
        if self.server.api_token_path is not None:
            server_data["api_token_path"] = self.server.api_token_path

        data = {
            "server": server_data,
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
