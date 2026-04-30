"""LM Studio CLI subprocess wrapper.

Provides programmatic access to the `lms` command-line tool for
model loading with GPU offload control, TTL auto-unload, and
accurate VRAM estimation — features not available via the REST API.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class MemoryEstimate:
    """Parsed output from `lms load --estimate-only`."""

    gpu_memory_gb: float
    total_memory_gb: float
    feasibility: str  # human-readable string from lms output


class LmsCliError(Exception):
    """Raised when the `lms` subprocess exits with a non-zero return code."""


class LmsCli:
    """Wrapper around the `lms` CLI binary for model load operations.

    Falls back gracefully: callers should check ``LmsCli.discover()``
    and use the REST API if it returns ``None``.
    """

    def __init__(
        self,
        binary_path: Path,
        host: str = "localhost",
        port: int = 1234,
    ) -> None:
        self.binary_path = Path(binary_path)
        self.host = host
        self.port = port

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def discover(override_path: Optional[str] = None) -> Optional["LmsCli"]:
        """Locate the lms binary and return an LmsCli instance, or None.

        Search order:
        1. ``override_path`` (if provided and the file exists)
        2. ``~/.lmstudio/bin/lms``
        3. ``which lms`` (PATH lookup)
        """
        candidates: list[Path] = []

        if override_path:
            candidates.append(Path(override_path).expanduser())

        candidates.append(Path.home() / ".lmstudio" / "bin" / "lms")

        which = shutil.which("lms")
        if which:
            candidates.append(Path(which))

        for path in candidates:
            if path.exists() and path.is_file():
                return LmsCli(binary_path=path)

        return None

    # ------------------------------------------------------------------
    # Argument helpers
    # ------------------------------------------------------------------

    def _gpu_arg(self, gpu_offload_percent: int) -> str:
        """Convert int to lms --gpu string.

        -1  → "max"
         0  → "off"
        1-100 → fraction string, e.g. 75 → "0.75"
        """
        if gpu_offload_percent < 0:
            return "max"
        if gpu_offload_percent == 0:
            return "off"
        return f"{gpu_offload_percent / 100:.2f}".rstrip("0").rstrip(".")

    def _host_args(self) -> list[str]:
        """Return --host flag args for non-localhost servers, else []."""
        if self.host in ("localhost", "127.0.0.1"):
            return []
        return ["--host", f"{self.host}:{self.port}"]

    # ------------------------------------------------------------------
    # Subprocess operations
    # ------------------------------------------------------------------

    async def load_model(
        self,
        model_key: str,
        context_length: int,
        gpu_offload_percent: int,
        ttl: Optional[int] = None,
    ) -> None:
        """Run `lms load` to load a model with full parameter control.

        Args:
            model_key: LM Studio model identifier.
            context_length: Context window size in tokens.
            gpu_offload_percent: -1=max, 0=off, 1-100=percent.
            ttl: Auto-unload after this many idle seconds; None=disabled.

        Raises:
            LmsCliError: If the subprocess exits with a non-zero code.
            asyncio.TimeoutError: If the load takes longer than 120 s.
        """
        cmd = [
            str(self.binary_path),
            "load",
            model_key,
            "--context-length", str(context_length),
            "--gpu", self._gpu_arg(gpu_offload_percent),
        ]
        if ttl is not None:
            cmd += ["--ttl", str(ttl)]
        cmd += self._host_args()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)

        if proc.returncode != 0:
            raise LmsCliError(stderr.decode(errors="replace").strip())

    async def estimate_memory(
        self,
        model_key: str,
        context_length: int,
        gpu_offload_percent: int,
    ) -> MemoryEstimate:
        """Run `lms load --estimate-only` and return parsed memory estimate.

        Raises:
            LmsCliError: If the subprocess exits with a non-zero code.
            asyncio.TimeoutError: If the command takes longer than 30 s.
        """
        cmd = [
            str(self.binary_path),
            "load",
            model_key,
            "--context-length", str(context_length),
            "--gpu", self._gpu_arg(gpu_offload_percent),
            "--estimate-only",
        ]
        cmd += self._host_args()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        if proc.returncode != 0:
            raise LmsCliError(stderr.decode(errors="replace").strip())

        # lms writes estimate output to stderr, not stdout
        return LmsCli._parse_estimate(stderr.decode(errors="replace"))

    @staticmethod
    def _parse_estimate(output: str) -> MemoryEstimate:
        """Parse stdout from `lms load --estimate-only`.

        Returns zeros with an empty feasibility string on parse failure
        rather than raising, so callers can handle gracefully.
        """
        gpu_match = re.search(r"Estimated GPU Memory:\s*([\d.]+)\s*GB", output)
        total_match = re.search(r"Estimated Total Memory:\s*([\d.]+)\s*GB", output)
        feasibility_match = re.search(r"Estimate:\s*(.+)", output)

        gpu_memory_gb = float(gpu_match.group(1)) if gpu_match else 0.0
        total_memory_gb = float(total_match.group(1)) if total_match else 0.0
        feasibility = feasibility_match.group(1).strip() if feasibility_match else ""

        return MemoryEstimate(
            gpu_memory_gb=gpu_memory_gb,
            total_memory_gb=total_memory_gb,
            feasibility=feasibility,
        )
