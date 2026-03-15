# Changelog

All notable changes to Lieutenant-Underwood are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [0.4.2] - 2026-03-15

### Fixed
- **Chat input text hidden when focused** — Textual's internal `Input:focus` component CSS re-applies `border: tall` at a higher specificity than a parent-selector rule, placing box-drawing characters over the typed text. Added an explicit `ChatPanel Input:focus { border: none; background: $surface-lighten-1 }` rule to override it. The blinking cursor is now the only focus indicator; no more invisible text until tabbing away.

---

## [0.4.1] - 2026-03-15

### Fixed
- **Chat history area too small** — `VerticalScroll.chat-history` had a fixed `height: 8`, leaving blank space below the input and giving model replies only 8 rows. Changed to `height: 1fr` so the history expands to fill all available panel space.
- **Chat panel not filling allocated space** — `ChatPanel` CSS had `height: auto`; changed to `height: 100%` so it correctly fills the `1fr` height assigned by the main screen layout.
- **Chat input too thin to see typed text** — Input height raised from `1` to `3` with `padding: 1 1`; `margin-top` removed. Text is now clearly visible without needing to change focus.
- **Theme palette: no way to identify current or default theme** — Replaced Textual's built-in `ThemeProvider` with `_MarkedThemeProvider` that appends `(current)` to the active theme and `(default)` to `textual-dark` in the picker list. A toast notification confirms every theme change. Palette placeholder updated to "Search themes… (current/default marked)".

---

## [0.4.0] - 2026-03-14

### Added
- **CPU STATUS panel** — New read-only informational panel between GPU STATUS and CHAT displaying five columns: CPU model name, free RAM, RAM used by LM Studio, system CPU utilization %, LM Studio CPU %
- `psutil` dependency for CPU and process monitoring
- `src/lmstudio_tui/cpu/monitor.py` — `CPUMonitor` class mirroring `GPUMonitor` pattern; reads `/proc/cpuinfo` for CPU model name; detects LM Studio process by name or cmdline path
- CPU update worker in `app.py` running alongside the existing GPU worker

### Changed
- Download status button changes from **✗ Cancel** to **✓ Close** when a download completes; clicking Close dismisses the download status frame
- Chat panel title changed from `CHAT / DOWNLOAD` to `CHAT`
- Left-column layout: GPU STATUS and CPU STATUS panels use `height: auto`; CHAT panel expands to fill remaining space (`height: 1fr`)

### Fixed
- **Graphical artifacts in PuTTY / SSH terminals** — Removed `border: solid` from `VerticalScroll.chat-history` and `border: tall` from the chat `Input` widget; these Unicode box-drawing characters rendered as block rectangles in PuTTY. Focus indicator preserved as `border-left: tall $primary` on the scroll container
- **Startup banner version** — `launcher.py` now imports `__version__` and renders the version dynamically; was previously hardcoded to `v0.2.0`
- **Install script** (`scripts/install.sh`) completely rewritten:
  - Creates a proper Python venv at `/opt/lieutenant-underwood/venv/`
  - Launcher uses `$VENV_DIR/bin/python` directly (no PATH manipulation)
  - Non-editable `pip install` for production installs
  - `--upgrade` mode: stops running instance, downloads latest, replaces source, `pip install --upgrade`
  - `--uninstall` mode: runs embedded uninstaller, which calls `pip uninstall -y lmstudio-tui` before removing files
  - Config path corrected to `~/.config/lmstudio-tui/` (was `~/.config/lmstui/`)
  - `CHANGELOG.md` copy guarded with `[ -f ... ]` to handle repos without it
  - Minimum Python version corrected to 3.9 (was 3.10)
  - Prompts before overwriting an existing install; suggests `--upgrade`

---

## [0.3.2] - 2026-03-10

### Added
- **Download progress monitoring** — Downloads from the model browser now run as detached subprocesses (`subprocess.Popen(start_new_session=True)`) so they survive TUI restarts
- `/tmp/ltu-download-state.json` state file allows a restarted TUI to resume monitoring an in-progress download
- `/tmp/ltu-download.log` captures `lms get` output; last meaningful line displayed live as the progress indicator
- `ANSI_ESCAPE` regex strips terminal colour/cursor codes from `lms get` stderr before display
- Download monitor worker (`_download_monitor_worker`) in `app.py` polls every 2 seconds, updates the `download_progress` ReactiveVar, and notifies on completion or error
- **Cancel download** button in Models panel; sends `SIGTERM` to the download process
- `DownloadProgress` dataclass in `store.py` (model_key, progress_line, elapsed_seconds, is_running, error)

### Changed
- Model browser `_start_download()` is now synchronous and calls `cli.start_download_detached()` instead of the previous async `_do_download()` method

---

## [0.3.0] - 2026-03-05

### Added
- **Hybrid CLI+API load path** — `lms load` subprocess used when the `lms` binary is available, unlocking:
  - **GPU layer offload** (`--gpu`) — fraction range 0–1, `off`, or `max`; enables partial CPU offload for models larger than available VRAM
  - **TTL auto-unload** (`--ttl`) — automatically unload after N seconds of inactivity (1 min / 5 min / 30 min / 1 hour / Off)
  - **Real VRAM estimation** via `lms load --estimate-only` — replaces the previous math-formula approximation with actual values from LM Studio
- `src/lmstudio_tui/cli/lms_cli.py` — `LmsCli` class: `discover()`, `load_model()`, `estimate_memory()`, `start_download_detached()`, `_parse_estimate()` and download state helpers
- `store.initialize_lms_cli()` — discovers `lms` binary on startup; stores reference in `RootStore`
- CLI status indicator in MODELS panel: **⚡ lms CLI: active** or **⚠ lms CLI not found — REST fallback active**
- **TTL selector** in MODELS panel LOAD CONFIGURATION frame (replaces KV Cache Quantization selector, which had no equivalent in `lms load`)
- **CALCULATE button** uses `lms load --estimate-only` for real estimates when `lms` is available; color-codes result green/yellow/red based on available VRAM
- `lms_cli_path` field in `AppConfig` (`[app]` section of config) for overriding the `lms` binary path
- **Model browser screen** (`model_browser_screen.py`) — Hugging Face model search via `lms search`, download via `lms get -y`, reachable with `d` from the MODELS panel
- `tests/test_lms_cli.py` — comprehensive unit tests for LmsCli using `AsyncMock`

### Changed
- `ModelLoadConfig` gains `ttl: Optional[int]` field; `kv_cache_quantization` retained only for REST API fallback
- MODELS panel GPU Offload selector now controls actual `--gpu` fraction passed to `lms load`
- REST API fallback for load shows a notification warning when `lms` CLI is not available
- `model_detail_screen.py` updated to show TTL instead of KV Cache Quantization; uses CLI load path

### Removed
- KV Cache Quantization selector removed from primary LOAD CONFIGURATION UI (not supported by `lms load`)

---

## [0.2.0] - 2026-02-28

### Added
- API token authentication in `LMStudioClient.from_config()` — reads token from `~/.lmstudio/token` or configurable path
- `ChatConfig.system_prompt` — configurable system prompt prepended to every chat conversation
- `format_size()` and `extract_quantization()` utility functions moved to `src/lmstudio_tui/utils.py`
- Example config trimmed to only document sections that are actually parsed

### Changed
- `LMStudioApp.__init__` now accepts `host` and `port` arguments; launcher passes the auto-detected values so the TUI connects to the discovered server immediately
- Config path unified to `~/.config/lmstudio-tui/config.toml` (previous launcher used `~/.config/lmstui/`)
- `disconnect_from_server()` is now `async` and is properly awaited in `on_shutdown()`
- Chat streaming refactored: the stream loop runs as a cancellable `asyncio.Task` stored in `_current_stream_task`, enabling reliable cancellation and the 30-second timeout monitor
- GPU panel `_restore_data_table()` re-creates the `DataTable` widget after an error clears, restoring column headers
- Python version check in launcher lowered to 3.9 (matching `pyproject.toml`)
- Default LM Studio port corrected to 1234 (was incorrectly 1235 in `ServerConfig`)
- Models poll error message now shows `host:port` and a retry countdown

### Fixed
- Chat stream timeout — 30-second watchdog checks GPU utilization as a secondary signal; cancels stalled streams gracefully with a user-visible error message
- GPU panel headers now render correctly on app startup (initialization timing fix)
- TOCTOU race condition in `gpu_monitor` access during concurrent shutdown eliminated via atomic reference capture pattern
- Non-functional "Change Context" button removed from model detail screen
- Dead `GPUCard` widget removed from `gpu_panel.py`
- `zeroconf` and `psutil` (v0.1.0 era) removed from `pyproject.toml`; `psutil` re-added in v0.4.0 for CPU monitoring

---

## [0.1.0] - 2026-02-20

### Added
- Initial project structure with Textual TUI framework
- **GPU monitoring** via PyNVML — utilization, VRAM, temperature, power draw
- **Models panel** — list models from LM Studio REST API with load/unload actions
- **Chat panel** — send messages to loaded models via `/v1/chat/completions` SSE streaming
- **Config management** — TOML config at `~/.config/lmstudio-tui/config.toml` with dacite deserialization
- **API client** — httpx-based async client for LM Studio `/api/v1/` endpoints
- Reactive state store (`RootStore`) with custom `ReactiveVar` pattern
- ASCII logo banner
- Launcher (`lmstui` command) with pre-flight checks (Python version, LM Studio detection, port auto-detect)
- MIT license
