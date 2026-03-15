"""Unit tests for lms CLI subprocess wrapper."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lmstudio_tui.cli.lms_cli import LmsCli, LmsCliError, MemoryEstimate


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_discover_finds_lmstudio_bin(self, tmp_path):
        """Discovers lms binary at ~/.lmstudio/bin/lms when it exists."""
        fake_lms = tmp_path / "lms"
        fake_lms.touch()

        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True):
            cli = LmsCli.discover(override_path=str(fake_lms))

        assert cli is not None
        assert cli.binary_path == fake_lms

    def test_discover_returns_none_when_not_found(self):
        """Returns None when no lms binary can be located."""
        with patch.object(Path, "exists", return_value=False), \
             patch("shutil.which", return_value=None):
            cli = LmsCli.discover()

        assert cli is None

    def test_discover_uses_which_fallback(self, tmp_path):
        """Falls back to PATH lookup via shutil.which."""
        fake_lms = tmp_path / "lms"
        fake_lms.touch()

        # ~/.lmstudio/bin/lms does NOT exist; PATH lms does
        def exists_side_effect(self):
            return self == fake_lms

        def is_file_side_effect(self):
            return self == fake_lms

        with patch.object(Path, "exists", exists_side_effect), \
             patch.object(Path, "is_file", is_file_side_effect), \
             patch("shutil.which", return_value=str(fake_lms)):
            cli = LmsCli.discover()

        assert cli is not None


# ---------------------------------------------------------------------------
# _gpu_arg conversion
# ---------------------------------------------------------------------------


class TestGpuArg:
    @pytest.fixture
    def cli(self, tmp_path):
        return LmsCli(binary_path=tmp_path / "lms")

    @pytest.mark.parametrize(
        "percent,expected",
        [
            (-1, "max"),
            (0, "off"),
            (50, "0.5"),
            (75, "0.75"),
            (100, "1"),
            (25, "0.25"),
        ],
    )
    def test_gpu_arg_conversion(self, cli, percent, expected):
        assert cli._gpu_arg(percent) == expected


# ---------------------------------------------------------------------------
# _host_args
# ---------------------------------------------------------------------------


class TestHostArgs:
    def test_host_args_localhost(self, tmp_path):
        cli = LmsCli(binary_path=tmp_path / "lms", host="localhost", port=1234)
        assert cli._host_args() == []

    def test_host_args_loopback(self, tmp_path):
        cli = LmsCli(binary_path=tmp_path / "lms", host="127.0.0.1", port=1234)
        assert cli._host_args() == []

    def test_host_args_remote(self, tmp_path):
        cli = LmsCli(binary_path=tmp_path / "lms", host="192.168.1.1", port=1234)
        assert cli._host_args() == ["--host", "192.168.1.1:1234"]


# ---------------------------------------------------------------------------
# load_model
# ---------------------------------------------------------------------------


class TestLoadModel:
    @pytest.fixture
    def cli(self, tmp_path):
        return LmsCli(binary_path=tmp_path / "lms", host="localhost", port=1234)

    @pytest.mark.asyncio
    async def test_load_model_success(self, cli):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            await cli.load_model(
                model_key="my-model",
                context_length=8192,
                gpu_offload_percent=-1,
            )

    @pytest.mark.asyncio
    async def test_load_model_failure_raises(self, cli):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: model not found"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(LmsCliError, match="model not found"):
                await cli.load_model(
                    model_key="bad-model",
                    context_length=8192,
                    gpu_offload_percent=-1,
                )

    @pytest.mark.asyncio
    async def test_load_model_timeout_raises(self, cli):
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(asyncio.TimeoutError):
                await cli.load_model(
                    model_key="slow-model",
                    context_length=8192,
                    gpu_offload_percent=50,
                )

    @pytest.mark.asyncio
    async def test_load_model_includes_ttl(self, cli):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await cli.load_model(
                model_key="my-model",
                context_length=8192,
                gpu_offload_percent=-1,
                ttl=300,
            )

        cmd = mock_exec.call_args[0]
        assert "--ttl" in cmd
        assert "300" in cmd


# ---------------------------------------------------------------------------
# estimate_memory
# ---------------------------------------------------------------------------

SAMPLE_ESTIMATE_OUTPUT = """\
Model: my-model
Estimated GPU Memory: 8.50 GB
Estimated Total Memory: 10.20 GB
Estimate: Fits within available VRAM
"""


class TestEstimateMemory:
    @pytest.fixture
    def cli(self, tmp_path):
        return LmsCli(binary_path=tmp_path / "lms", host="localhost", port=1234)

    @pytest.mark.asyncio
    async def test_estimate_memory_success(self, cli):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        # lms writes estimate output to stderr, not stdout
        mock_proc.communicate = AsyncMock(
            return_value=(b"", SAMPLE_ESTIMATE_OUTPUT.encode())
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await cli.estimate_memory(
                model_key="my-model",
                context_length=8192,
                gpu_offload_percent=-1,
            )

        assert result.gpu_memory_gb == pytest.approx(8.5)
        assert result.total_memory_gb == pytest.approx(10.2)
        assert "Fits" in result.feasibility


# ---------------------------------------------------------------------------
# _parse_estimate (static)
# ---------------------------------------------------------------------------


class TestParseEstimate:
    def test_parse_estimate_valid_output(self):
        result = LmsCli._parse_estimate(SAMPLE_ESTIMATE_OUTPUT)
        assert result.gpu_memory_gb == pytest.approx(8.5)
        assert result.total_memory_gb == pytest.approx(10.2)
        assert result.feasibility == "Fits within available VRAM"

    def test_parse_estimate_malformed_output(self):
        result = LmsCli._parse_estimate("No useful output here")
        assert result.gpu_memory_gb == 0.0
        assert result.total_memory_gb == 0.0
        assert result.feasibility == ""

    def test_parse_estimate_partial_output(self):
        output = "Estimated GPU Memory: 4.00 GB\nSomething else"
        result = LmsCli._parse_estimate(output)
        assert result.gpu_memory_gb == pytest.approx(4.0)
        assert result.total_memory_gb == 0.0
        assert result.feasibility == ""
