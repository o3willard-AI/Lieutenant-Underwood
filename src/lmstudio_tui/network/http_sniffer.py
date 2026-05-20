"""Passive HTTP sniffer for LM Studio inference traffic.

Monitors all network interfaces for plain HTTP traffic on the LM Studio port
and feeds request counts, TTFT, and token chunk counts directly into the store.

Requires CAP_NET_RAW or root.  Falls back gracefully if scapy is absent or
privileges are insufficient — all other panel metrics remain functional.

Port tracking: call update_port() to restart the sniffer on a new port.
app.py's _port_watch_worker polls store.config.value.server.port every 5 s
and calls update_port() on change, so the sniffer follows config edits without
a TUI restart.

Token counting: LM Studio streams one SSE event per output token.  Each packet
from the server containing "data: {" has that many token chunks.  We count
occurrences of b"data: {" in the raw TCP payload — fast, allocation-free, and
accurate for the typical 1-event-per-packet streaming pattern.  Packets that
happen to span multiple events are still counted correctly.

TTFT: measured from the TCP SYN timestamp to the first packet that contains a
token event (b"data: {"), which closely matches the wall-clock TTFT a client
would observe.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import scapy.all as _scapy_probe  # noqa: F401 — test import only
    _SCAPY_AVAILABLE = True
except ImportError:
    _SCAPY_AVAILABLE = False


@dataclass
class _ConnState:
    """Per-TCP-connection tracking state."""
    start_time: float = field(default_factory=time.time)
    first_token_seen: bool = False


class HTTPSniffer:
    """Passive sniffer that counts requests and tokens from LM Studio HTTP traffic.

    Thread-safe.  update_port() stops the current sniffer thread and starts a
    new one on the new port within ~1 s (scapy's sniff timeout), preserving all
    session-level store counters.
    """

    def __init__(self, store) -> None:
        self._store = store
        self._port: int = 0
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._conn_lock = threading.Lock()
        self._connections: dict[tuple, _ConnState] = {}
        # Public status flags (read by app.py for notifications)
        self.available: bool = _SCAPY_AVAILABLE
        self.privileged: bool = True

    @property
    def port(self) -> int:
        return self._port

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self, port: int) -> bool:
        """Start sniffing on *port*.  Returns False if scapy is not installed."""
        if not _SCAPY_AVAILABLE:
            logger.warning("scapy not installed — network sniffer disabled")
            self.available = False
            return False
        self._port = port
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._sniff_loop, daemon=True, name="http_sniffer"
        )
        self._thread.start()
        logger.info(f"HTTP sniffer started on port {port}")
        return True

    def update_port(self, new_port: int) -> None:
        """Switch to *new_port*, restarting the sniffer thread."""
        if new_port == self._port or not self.available:
            return
        old = self._port
        self._stop_flag.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._port = new_port
        with self._conn_lock:
            self._connections.clear()
        self._stop_flag.clear()
        self._thread = threading.Thread(
            target=self._sniff_loop, daemon=True, name="http_sniffer"
        )
        self._thread.start()
        logger.info(f"HTTP sniffer: port {old} → {new_port}")

    def stop(self) -> None:
        self._stop_flag.set()

    # ── Sniffer thread ───────────────────────────────────────────────────────

    def _sniff_loop(self) -> None:
        from scapy.all import sniff
        port = self._port
        try:
            while not self._stop_flag.is_set():
                # timeout=1 so the stop flag is checked every second
                sniff(
                    filter=f"tcp port {port}",
                    prn=self._handle_packet,
                    store=False,
                    timeout=1,
                )
        except PermissionError:
            self._log_privilege_error()
        except Exception as e:
            if "Operation not permitted" in str(e) or "Permission denied" in str(e):
                self._log_privilege_error()
            else:
                logger.error(f"HTTP sniffer error: {e}", exc_info=True)

    def _log_privilege_error(self) -> None:
        self.available = False
        self.privileged = False
        logger.error(
            "HTTP sniffer: insufficient privileges (CAP_NET_RAW required). "
            "Re-run the installer to restore: sudo bash install.sh --upgrade"
        )

    # ── Packet handler ───────────────────────────────────────────────────────

    def _handle_packet(self, pkt) -> None:  # noqa: C901
        try:
            from scapy.all import IP, TCP, Raw
            if not pkt.haslayer(TCP) or not pkt.haslayer(IP):
                return

            tcp = pkt[TCP]
            port = self._port

            # New TCP connection: SYN without ACK (flags == 0x002)
            if tcp.flags == 0x002 and tcp.dport == port:
                key = (pkt[IP].src, tcp.sport)
                with self._conn_lock:
                    self._connections[key] = _ConnState()
                return

            # Only care about server→client payload from here on
            if tcp.sport != port or not pkt.haslayer(Raw):
                return

            payload: bytes = pkt[Raw].load
            client_key = (pkt[IP].dst, tcp.dport)

            with self._conn_lock:
                state = self._connections.get(client_key)

            # Count SSE token events: each b"data: {" ≈ 1 output token
            token_count = payload.count(b"data: {")
            if token_count > 0:
                # First token in this connection → record TTFT
                if state and not state.first_token_seen:
                    # Double-check under lock to avoid a race
                    with self._conn_lock:
                        if not state.first_token_seen:
                            state.first_token_seen = True
                            ttft = time.time() - state.start_time
                    self._store.record_network_first_token(ttft)
                self._store.record_network_token_chunk(token_count)

            # Stream done → request complete
            if b"data: [DONE]" in payload:
                self._store.record_network_request_complete()
                with self._conn_lock:
                    self._connections.pop(client_key, None)

        except Exception as e:
            logger.debug(f"HTTP sniffer packet handler: {e}")
