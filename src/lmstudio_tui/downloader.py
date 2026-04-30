"""Direct HF streaming downloader — bypasses `lms get` for model downloads.

`lms get` is a catalog-search tool designed for LM Studio's curated model list.
Most Hugging Face publishers are not in that catalog, so `lms get` either fails
silently or prompts interactively (which kills the process when stdin is closed).

This module streams GGUF files directly from huggingface.co using httpx (already
a project dependency), writing real-time byte/speed progress to the RootStore so
the UI can display accurate progress rather than tailing a log file.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import httpx

if TYPE_CHECKING:
    from lmstudio_tui.store import RootStore

logger = logging.getLogger(__name__)

_HF_BASE = "https://huggingface.co"
_UPDATE_INTERVAL_SECS = 0.5  # max UI progress update frequency


def detect_lmstudio_models_dir() -> Path:
    """Return the LM Studio models directory, creating it if absent.

    LM Studio stores models at ~/.lmstudio/models/ on all supported platforms.
    The directory hierarchy is {models_dir}/{publisher}/{repo-name}/{file.gguf},
    mirroring the Hugging Face repo structure so LM Studio can index them.
    """
    path = Path.home() / ".lmstudio" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def fetch_gguf_files(repo_id: str) -> list[dict]:
    """Return a sorted list of GGUF files available in a Hugging Face repo.

    Uses the HF API ``?blobs=true`` parameter to retrieve file sizes alongside
    filenames in a single request.

    Args:
        repo_id: Hugging Face repo identifier (e.g. "bartowski/Qwen2.5-7B-Instruct-GGUF").

    Returns:
        List of dicts with keys ``name`` (str) and ``size`` (int bytes), sorted
        alphabetically by name.

    Raises:
        httpx.HTTPStatusError: If the HF API returns a non-2xx status.
        httpx.TimeoutException: If the request times out.
    """
    url = f"{_HF_BASE}/api/models/{repo_id}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, params={"blobs": "true"})
        response.raise_for_status()
        data = response.json()

    files = [
        {"name": s["rfilename"], "size": s.get("size", 0)}
        for s in data.get("siblings", [])
        if s.get("rfilename", "").lower().endswith(".gguf")
    ]
    files.sort(key=lambda f: f["name"])
    return files


async def stream_download(
    repo_id: str,
    filename: str,
    dest_dir: Path,
    store: "RootStore",
) -> None:
    """Stream-download a single GGUF file from Hugging Face to dest_dir.

    Designed to run as an app-level Textual worker so it outlives any modal
    screen that initiates it.  Progress is written to ``store.download_progress``
    at most twice per second to keep the UI responsive.

    On cancellation or error the partial file is cleaned up.  On success the
    file lives at ``dest_dir / filename`` for LM Studio to index on next scan.

    Args:
        repo_id: HF repo ID, e.g. ``"bartowski/Qwen2.5-7B-Instruct-GGUF"``.
        filename: Specific GGUF filename within that repo.
        dest_dir: Local directory to write into (created if absent).
        store: RootStore singleton for progress reporting.
    """
    from lmstudio_tui.store import DownloadProgress

    url = f"{_HF_BASE}/{repo_id}/resolve/main/{filename}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    start_time = time.monotonic()
    bytes_received = 0
    total_bytes = 0
    last_update = start_time

    def _push(*, is_running: bool = True, error: Optional[str] = None) -> None:
        elapsed = time.monotonic() - start_time
        speed = bytes_received / elapsed if elapsed > 0 else 0.0
        store.download_progress.value = DownloadProgress(
            model_key=repo_id,
            filename=filename,
            bytes_received=bytes_received,
            total_bytes=total_bytes,
            elapsed_seconds=elapsed,
            speed_bps=speed,
            is_running=is_running,
            error=error,
        )

    _push()  # initial "Connecting…" state

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=300.0, write=None, pool=None),
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total_bytes = int(response.headers.get("content-length", 0))
                _push()  # update with known file size

                with open(dest_path, "wb") as fh:
                    async for chunk in response.aiter_bytes(chunk_size=512 * 1024):
                        fh.write(chunk)
                        bytes_received += len(chunk)
                        now = time.monotonic()
                        if now - last_update >= _UPDATE_INTERVAL_SECS:
                            last_update = now
                            _push()

        _push(is_running=False)
        logger.info("Download complete: %s/%s → %s", repo_id, filename, dest_path)

    except asyncio.CancelledError:
        _remove_partial(dest_path)
        _push(is_running=False, error="Cancelled")
        raise

    except Exception as exc:
        logger.error("Download failed for %s/%s: %s", repo_id, filename, exc)
        _remove_partial(dest_path)
        _push(is_running=False, error=str(exc))


def _remove_partial(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
