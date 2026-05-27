"""HTTP sniffer using tcpdump subprocess.

Replaces the in-process scapy approach (v0.8.4–0.8.6) which caused
significant network throughput degradation. The root causes were:

1. AF_PACKET/ETH_P_ALL socket — the kernel delivers a copy of every
   ethernet frame to the socket for BPF evaluation, adding per-packet
   overhead to all traffic on the interface regardless of the filter.

2. GIL contention — running scapy's packet callback in a Python thread
   starved the asyncio event loop, throttling httpx downloads via TCP
   receive-window starvation (visible as ~366 bytes/sec HF downloads).

tcpdump runs as a completely separate process: its own memory space, no
shared GIL, efficient kernel BPF that delivers only matching packets to
userspace. Performance impact on the host is negligible.

Requires: tcpdump installed with cap_net_raw capability.
Grant:    sudo setcap cap_net_raw+eip $(which tcpdump)
          (done automatically by install.sh)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class HTTPSniffer:
    """Passive sniffer that counts LM Studio requests and token chunks.

    Spawns tcpdump as a child process and reads its line-buffered ASCII
    output.  Only packets matching ``tcp port <port>`` reach the reader;
    all other traffic is filtered in the kernel before reaching Python.
    """

    def __init__(self, store) -> None:
        self._store = store
        self._port: int = 0
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self.available: bool = True
        self.privileged: bool = True

    @property
    def port(self) -> int:
        return self._port

    @staticmethod
    def _find_tcpdump() -> Optional[str]:
        for candidate in (
            shutil.which("tcpdump"),
            "/usr/bin/tcpdump",
            "/usr/sbin/tcpdump",
        ):
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self, port: int) -> bool:
        """Start sniffing on *port*.  Returns False if tcpdump is not found."""
        tcpdump = self._find_tcpdump()
        if not tcpdump:
            logger.warning("tcpdump not found — network sniffer disabled")
            self.available = False
            return False
        self._port = port
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._run, args=(tcpdump,), daemon=True, name="http_sniffer"
        )
        self._thread.start()
        logger.info(f"HTTP sniffer (tcpdump) started on port {port}")
        return True

    def update_port(self, new_port: int) -> None:
        """Switch to *new_port*, restarting the tcpdump child process."""
        if new_port == self._port or not self.available:
            return
        old = self._port
        self._stop_flag.set()
        self._kill_proc()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._port = new_port
        self._stop_flag.clear()
        tcpdump = self._find_tcpdump()
        if tcpdump:
            self._thread = threading.Thread(
                target=self._run, args=(tcpdump,), daemon=True, name="http_sniffer"
            )
            self._thread.start()
        logger.info(f"HTTP sniffer: port {old} → {new_port}")

    def stop(self) -> None:
        self._stop_flag.set()
        self._kill_proc()

    def _kill_proc(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._proc = None

    # ── tcpdump reader loop ──────────────────────────────────────────────────

    def _run(self, tcpdump: str) -> None:
        port = self._port
        try:
            self._proc = subprocess.Popen(
                [
                    tcpdump,
                    "-l",         # line-buffered stdout — essential for low latency
                    "-n",         # no DNS resolution
                    "-A",         # print payload as ASCII
                    "-q",         # quiet (compact packet header)
                    "-i", "any",  # all interfaces (loopback + ethernet)
                    f"tcp port {port}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except PermissionError:
            self._log_priv_error()
            return
        except Exception as e:
            logger.error(f"HTTP sniffer: failed to launch tcpdump: {e}")
            self.available = False
            return

        # Give tcpdump 300 ms to start; check for immediate exit (e.g. permission error)
        time.sleep(0.3)
        if self._proc.poll() is not None:
            err = self._proc.stderr.read().decode(errors="replace").lower()
            if "permission" in err or "not permitted" in err:
                self._log_priv_error()
            else:
                logger.error(f"HTTP sniffer: tcpdump exited unexpectedly: {err[:200]}")
                self.available = False
            return

        logger.info(f"HTTP sniffer: tcpdump running (pid {self._proc.pid})")

        req_start: Optional[float] = None
        first_token_seen = False

        try:
            for raw in self._proc.stdout:
                if self._stop_flag.is_set():
                    break
                line = raw.decode("latin-1", errors="replace")

                # Detect new chat completion request (client→server direction)
                if "/v1/chat/completions" in line:
                    req_start = time.time()
                    first_token_seen = False

                # Count SSE token events: each "data: {" ≈ 1 output token
                if "data: {" in line:
                    # First token of this request → measure TTFT
                    if req_start is not None and not first_token_seen:
                        ttft = time.time() - req_start
                        self._store.record_network_first_token(ttft)
                        first_token_seen = True
                    self._store.record_network_token_chunk(line.count("data: {"))

                # Stream finished → increment request counter and reset state
                if "data: [DONE]" in line:
                    self._store.record_network_request_complete()
                    req_start = None
                    first_token_seen = False

        except Exception as e:
            logger.debug(f"HTTP sniffer read loop: {e}")
        finally:
            self._kill_proc()

    def _log_priv_error(self) -> None:
        self.available = False
        self.privileged = False
        logger.error(
            "HTTP sniffer: tcpdump permission denied — "
            "run: sudo setcap cap_net_raw+eip $(which tcpdump)"
        )
