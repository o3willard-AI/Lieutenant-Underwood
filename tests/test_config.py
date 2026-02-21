"""Tests for TOML configuration loader."""
import tempfile
from pathlib import Path

from lmstudio_tui.config import AppConfig, ServerConfig, GPUConfig, AlertThresholds


def test_default_config():
    """Default config has expected values matching SCHEMA.toml defaults."""
    cfg = AppConfig.load(None)

    # Server defaults from SCHEMA.toml
    assert cfg.server.host == "localhost"
    assert cfg.server.port == 1234
    assert cfg.server.timeout == 10.0
    assert cfg.server.retry is True
    assert cfg.server.api_token_path == "~/.lmstudio/token"
    assert cfg.server.verify_ssl is True

    # GPU defaults from SCHEMA.toml
    assert cfg.gpu.monitoring_enabled is True
    assert cfg.gpu.update_frequency == 1.0

    # Alert thresholds from SCHEMA.toml
    assert cfg.gpu.alert_thresholds.temp_warning == 80
    assert cfg.gpu.alert_thresholds.temp_critical == 90
    assert cfg.gpu.alert_thresholds.vram_warning == 95
    assert cfg.gpu.alert_thresholds.vram_critical == 98


def test_load_from_toml():
    """Load from TOML file works correctly."""
    toml_content = """
[server]
host = "192.168.1.100"
port = 5678
timeout = 30.0
retry = false
api_token_path = "/custom/path/token"
verify_ssl = false

[gpu]
monitoring_enabled = false
update_frequency = 5.0

[alerts.temperature]
warning = 75
critical = 85

[alerts.vram]
warning = 90
critical = 95
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(toml_content)
        f.flush()
        temp_path = Path(f.name)

    try:
        cfg = AppConfig.load(temp_path)

        # Server config
        assert cfg.server.host == "192.168.1.100"
        assert cfg.server.port == 5678
        assert cfg.server.timeout == 30.0
        assert cfg.server.retry is False
        assert cfg.server.api_token_path == "/custom/path/token"
        assert cfg.server.verify_ssl is False

        # GPU config
        assert cfg.gpu.monitoring_enabled is False
        assert cfg.gpu.update_frequency == 5.0

        # Alert thresholds
        assert cfg.gpu.alert_thresholds.temp_warning == 75
        assert cfg.gpu.alert_thresholds.temp_critical == 85
        assert cfg.gpu.alert_thresholds.vram_warning == 90
        assert cfg.gpu.alert_thresholds.vram_critical == 95
    finally:
        temp_path.unlink(missing_ok=True)


def test_save_and_reload():
    """Save config and reload verifies round-trip."""
    # Create custom config
    original = AppConfig(
        server=ServerConfig(
            host="test-server.local",
            port=9999,
            timeout=5.0,
            retry=False,
            api_token_path="/test/token",
            verify_ssl=False,
        ),
        gpu=GPUConfig(
            monitoring_enabled=False,
            update_frequency=2.5,
            alert_thresholds=AlertThresholds(
                temp_warning=70,
                temp_critical=80,
                vram_warning=85,
                vram_critical=92,
            ),
        ),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.toml"

        # Save
        original.save(config_path)
        assert config_path.exists()

        # Reload
        loaded = AppConfig.load(config_path)

        # Verify round-trip
        assert loaded.server.host == original.server.host
        assert loaded.server.port == original.server.port
        assert loaded.server.timeout == original.server.timeout
        assert loaded.server.retry == original.server.retry
        assert loaded.server.api_token_path == original.server.api_token_path
        assert loaded.server.verify_ssl == original.server.verify_ssl

        assert loaded.gpu.monitoring_enabled == original.gpu.monitoring_enabled
        assert loaded.gpu.update_frequency == original.gpu.update_frequency

        assert loaded.gpu.alert_thresholds.temp_warning == original.gpu.alert_thresholds.temp_warning
        assert loaded.gpu.alert_thresholds.temp_critical == original.gpu.alert_thresholds.temp_critical
        assert loaded.gpu.alert_thresholds.vram_warning == original.gpu.alert_thresholds.vram_warning
        assert loaded.gpu.alert_thresholds.vram_critical == original.gpu.alert_thresholds.vram_critical


def test_missing_file_returns_defaults():
    """Missing config file returns default configuration."""
    cfg = AppConfig.load(Path("/nonexistent/path/config.toml"))

    assert cfg.server.host == "localhost"
    assert cfg.server.port == 1234
    assert cfg.gpu.monitoring_enabled is True
