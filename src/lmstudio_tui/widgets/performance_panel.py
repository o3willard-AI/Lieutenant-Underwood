"""Performance metrics panel for LM Studio TUI."""

from __future__ import annotations

from textual.containers import Container, Horizontal
from textual.widgets import Static

from lmstudio_tui.store import get_store


class PerformancePanel(Container):
    """Displays real-time inference performance metrics.

    Refreshes every second via set_interval. All counters accumulate
    while the TUI is running; they reset when the TUI restarts.
    """

    DEFAULT_CSS = """
    PerformancePanel {
        width: 100%;
        height: auto;
        padding: 1;
        border: solid $primary;
    }
    PerformancePanel Static.title {
        text-style: bold;
        color: $primary;
        height: 1;
    }
    PerformancePanel Horizontal.stats-row {
        width: 100%;
        height: auto;
        margin-top: 1;
    }
    PerformancePanel Static.stat {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    PerformancePanel Static.context-line {
        width: 100%;
        height: 1;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._store = get_store()
        self._tps_now_widget = None
        self._tps_peak_widget = None
        self._tps_avg_widget = None
        self._ttft_widget = None
        self._req_widget = None
        self._tok_widget = None
        self._ctx_widget = None

    def compose(self):
        yield Static("⚡ PERFORMANCE", classes="title")
        with Horizontal(classes="stats-row"):
            self._tps_now_widget = Static("", classes="stat", id="perf_tps_now")
            yield self._tps_now_widget
            self._tps_peak_widget = Static("", classes="stat", id="perf_tps_peak")
            yield self._tps_peak_widget
            self._tps_avg_widget = Static("", classes="stat", id="perf_tps_avg")
            yield self._tps_avg_widget
            self._ttft_widget = Static("", classes="stat", id="perf_ttft")
            yield self._ttft_widget
            self._req_widget = Static("", classes="stat", id="perf_req")
            yield self._req_widget
            self._tok_widget = Static("", classes="stat", id="perf_tok")
            yield self._tok_widget
        self._ctx_widget = Static("", classes="context-line", id="perf_ctx")
        yield self._ctx_widget

    def on_mount(self) -> None:
        self._refresh_display()
        self.set_interval(1.0, self._refresh_display)

    def _refresh_display(self) -> None:
        m = self._store.get_inference_metrics()

        # TPS (now) — highlight green when active, dim when idle; ~ prefix if estimated
        if self._tps_now_widget:
            if m.tps_current > 0.1:
                prefix = "~" if m.tps_is_estimated else ""
                self._tps_now_widget.update(
                    f"[dim]TPS (now)[/dim]\n[$success]{prefix}{m.tps_current:.1f} t/s[/]"
                )
            else:
                self._tps_now_widget.update(
                    f"[dim]TPS (now)[/dim]\n[dim]0.0 t/s[/dim]"
                )

        if self._tps_peak_widget:
            self._tps_peak_widget.update(
                f"[dim]TPS (peak)[/dim]\n{m.tps_peak:.1f} t/s"
            )

        if self._tps_avg_widget:
            self._tps_avg_widget.update(
                f"[dim]TPS (avg)[/dim]\n{m.tps_average:.1f} t/s"
            )

        if self._ttft_widget:
            if m.ttft_last3:
                avg_ms = sum(m.ttft_last3) / len(m.ttft_last3) * 1000
                n = len(m.ttft_last3)
                self._ttft_widget.update(f"[dim]TTFT avg[/dim]\n{avg_ms:.0f} ms ({n} req)")
            else:
                self._ttft_widget.update("[dim]TTFT avg[/dim]\n[dim]—[/dim]")

        if self._req_widget:
            self._req_widget.update(f"[dim]Requests[/dim]\n{m.total_requests}")

        if self._tok_widget:
            self._tok_widget.update(f"[dim]Tokens out[/dim]\n{m.total_tokens_out:,}")

        if self._ctx_widget:
            if m.last_context_size > 0 and m.last_prompt_tokens > 0:
                pct = min(100.0, m.last_prompt_tokens / m.last_context_size * 100)
                filled = int(pct / 5)
                bar = "█" * filled + "░" * (20 - filled)
                if pct < 70:
                    color = "$success"
                elif pct < 90:
                    color = "$warning"
                else:
                    color = "$error"
                self._ctx_widget.update(
                    f"[dim]Context:[/dim] [{color}]{m.last_prompt_tokens:,} / "
                    f"{m.last_context_size:,} tokens  {pct:.0f}%  {bar}[/]"
                )
            else:
                self._ctx_widget.update("[dim]Context: — (no requests yet)[/dim]")
