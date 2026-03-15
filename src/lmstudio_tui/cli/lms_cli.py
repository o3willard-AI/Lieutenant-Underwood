"""LM Studio CLI subprocess wrapper.

Provides programmatic access to the `lms` command-line tool for
model loading with GPU offload control, TTL auto-unload, and
accurate VRAM estimation — features not available via the REST API.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Strip ANSI escape sequences (used by lms for progress bars and colour output)
ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-9;]*[A-Za-z])")

DOWNLOAD_STATE_FILE = Path("/tmp/ltu-download-state.json")
DOWNLOAD_LOG_FILE = Path("/tmp/ltu-download.log")


@dataclass
class DownloadState:
    """Persisted state for a detached lms-get download process."""

    model_key: str
    pid: int
    log_file: str
    start_time: float

    def to_dict(self) -> dict:
        return {
            "model_key": self.model_key,
            "pid": self.pid,
            "log_file": self.log_file,
            "start_time": self.start_time,
        }

    @staticmethod
    def from_dict(d: dict) -> "DownloadState":
        return DownloadState(
            model_key=d["model_key"],
            pid=d["pid"],
            log_file=d["log_file"],
            start_time=d["start_time"],
        )


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

    async def download_model(self, model_key: str) -> None:
        """Run `lms get <model> --gguf -y` to download a model from HuggingFace.

        Download runs on the machine hosting LM Studio (where lms lives).
        No --host flag: lms get always downloads to the local models directory.

        Args:
            model_key: HuggingFace model ID (e.g. "bartowski/Llama-3.1-8B-GGUF").

        Raises:
            LmsCliError: If the subprocess exits with a non-zero code.
            asyncio.TimeoutError: If download exceeds 3600 s (1 hour).
        """
        cmd = [str(self.binary_path), "get", model_key, "--gguf", "-y"]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3600.0)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
            raise LmsCliError(err)

    # ------------------------------------------------------------------
    # Detached download (survives TUI restarts)
    # ------------------------------------------------------------------

    def start_download_detached(self, model_key: str) -> DownloadState:
        """Spawn a detached `lms get` process that outlives the TUI.

        The subprocess runs in its own session (start_new_session=True)
        so it is not killed when the parent Python process exits. Progress
        is written to DOWNLOAD_LOG_FILE and state is persisted to
        DOWNLOAD_STATE_FILE for recovery after a TUI restart.

        Args:
            model_key: HuggingFace model ID to download.

        Returns:
            DownloadState describing the running process.
        """
        cmd = [str(self.binary_path), "get", model_key, "-y"]
        with open(DOWNLOAD_LOG_FILE, "w") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        state = DownloadState(
            model_key=model_key,
            pid=proc.pid,
            log_file=str(DOWNLOAD_LOG_FILE),
            start_time=time.time(),
        )
        LmsCli._save_download_state(state)
        return state

    @staticmethod
    def _save_download_state(state: DownloadState) -> None:
        """Write download state to the state file."""
        try:
            with open(DOWNLOAD_STATE_FILE, "w") as f:
                json.dump(state.to_dict(), f)
        except Exception:
            pass

    @staticmethod
    def load_download_state() -> Optional[DownloadState]:
        """Load download state from disk, or return None if absent/corrupt."""
        try:
            if not DOWNLOAD_STATE_FILE.exists():
                return None
            with open(DOWNLOAD_STATE_FILE) as f:
                return DownloadState.from_dict(json.load(f))
        except Exception:
            return None

    @staticmethod
    def is_download_running(pid: int) -> bool:
        """Return True if the given PID is still alive."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Process exists but we cannot send signals to it

    @staticmethod
    def read_download_progress() -> str:
        """Return the last meaningful line from the download log (ANSI stripped)."""
        try:
            if not DOWNLOAD_LOG_FILE.exists():
                return ""
            with open(DOWNLOAD_LOG_FILE, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                raw = f.read()
            text = ANSI_ESCAPE.sub("", raw.decode(errors="replace"))
            text = text.replace("\r", "\n")
            for line in reversed(text.split("\n")):
                line = line.strip()
                if line:
                    return line
            return ""
        except Exception:
            return ""

    @staticmethod
    def clear_download_state() -> None:
        """Remove the download state file."""
        try:
            DOWNLOAD_STATE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def cancel_download() -> bool:
        """Send SIGTERM to the active download process.

        Returns:
            True if a running process was found and signalled, False otherwise.
        """
        state = LmsCli.load_download_state()
        if not state:
            return False
        try:
            os.kill(state.pid, signal.SIGTERM)
        except Exception:
            pass
        LmsCli.clear_download_state()
        return True

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
