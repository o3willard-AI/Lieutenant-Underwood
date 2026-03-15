# Lieutenant-Underwood — Developer Reference

**Current version:** 0.4.2
**Repository:** https://github.com/o3willard-AI/Lieutenant-Underwood
**Local clone:** `/home/sblanken/working/lms-tui/`
**License:** MIT

---

## What It Is

Lieutenant-Underwood (LTU) is a Python terminal user interface built with [Textual](https://textual.textualize.io/) for monitoring and managing an [LM Studio](https://lmstudio.ai/) headless inference server over its REST API and local `lms` CLI. It is designed for operators running LM Studio on dedicated hardware — particularly multi-GPU systems — who want a real-time dashboard without a web browser.

The name is a play on military brevity: **LT U** = **L**M-Studio **T**erminal **U**ser-interface.

---

## Current Feature Set (v0.4.2)

| Panel | Description |
|-------|-------------|
| **GPU STATUS** | Per-GPU table: utilization %, VRAM used/total, temperature °C, power draw W. NVIDIA only via PyNVML. |
| **CPU STATUS** | System-wide CPU model, free RAM, RAM used by LM Studio process, CPU util %, LM Studio CPU %. Uses psutil. |
| **MODELS** | Lists all models known to LM Studio with status (Loaded/Standby), size, and quantization. Keyboard-driven load/unload. |
| **LOAD CONFIGURATION** | Per-model load settings inline in the MODELS panel: GPU offload %, context length, TTL auto-unload. CALCULATE triggers real VRAM estimation. |
| **CHAT** | Single-turn and multi-turn chat against a loaded model via OpenAI-compatible SSE streaming. Slash commands for model switching and local imports. |
| **Model Browser** | Full-screen Hugging Face model search and download (`lms search` / `lms get`). |
| **Download Monitor** | Inline progress in MODELS panel. Downloads run as detached subprocesses and survive TUI restarts. |
| **Theme Switcher** | `Ctrl+P` → "Theme". Custom provider marks `(current)` and `(default)` themes; toast confirms changes. 20 themes. |

---

## Architecture

### Dependency Graph (high level)

```
launcher.py
    └── app.py  (LMStudioApp : Textual App)
            ├── store.py  (RootStore singleton — all shared state)
            │       ├── api/client.py  (httpx async REST client)
            │       ├── cli/lms_cli.py  (lms subprocess wrapper)
            │       ├── gpu/monitor.py  (PyNVML)
            │       └── cpu/monitor.py  (psutil)
            ├── config.py  (AppConfig dataclasses + TOML I/O)
            └── screens/
                    ├── main_screen.py
                    │       ├── widgets/gpu_panel.py
                    │       ├── widgets/cpu_panel.py
                    │       ├── widgets/chat_panel.py
                    │       └── widgets/models_panel.py
                    ├── model_detail_screen.py
                    └── model_browser_screen.py
```

---

### `store.py` — Singleton Reactive State

The central nervous system. `RootStore` is a **singleton** (Python `__new__` guard) holding all shared application state as `ReactiveVar[T]` instances.

**`ReactiveVar[T]`** is a custom generic class (not Textual's `reactive`) that:
- Lives outside the Textual DOM, so it can be safely set from asyncio workers and background threads
- Holds a list of `Callable[[old, new], None]` watchers registered via `.watch()`
- Uses a `threading.Lock` for watcher notification to prevent races
- Is intentionally NOT used as a Textual reactive to avoid triggering Textual's repaint machinery from worker threads

**Key ReactiveVars:**

| Variable | Type | Purpose |
|----------|------|---------|
| `config` | `AppConfig` | Loaded TOML config |
| `models` | `list[ModelInfo]` | All models from `/api/v1/models` |
| `active_model` | `Optional[str]` | Model ID selected for chat |
| `gpu_metrics` | `list[GPUMetrics]` | Latest GPU readings |
| `gpu_error` | `Optional[str]` | GPU monitor error string |
| `cpu_metrics` | `Optional[CPUMetrics]` | Latest CPU readings |
| `cpu_error` | `Optional[str]` | CPU monitor error string |
| `model_loading` | `bool` | Load operation in progress |
| `download_progress` | `Optional[DownloadProgress]` | Active download state |

**Important store methods:**
- `initialize_lms_cli(binary_path=None) -> bool` — discovers `lms` binary; sets `_lms_cli`
- `start_gpu_monitoring() -> bool` — initialises PyNVML; returns False if no NVIDIA GPU
- `start_cpu_monitoring() -> bool` — initialises psutil; returns False if unavailable
- `stop_gpu_monitoring()` / `stop_cpu_monitoring()` — called in `app.on_shutdown()`
- `connect_to_server()` / `disconnect_from_server()` (async) — creates/destroys httpx client

---

### `app.py` — Textual Application Root

`LMStudioApp(App)` manages the Textual event loop and background workers.

**Constructor:** Accepts `host` and `port` from the launcher (post-detection); loads config; applies overrides.

**`on_mount()`** starts four background workers via `self.run_worker(coro, name=...)`:

| Worker | Poll interval | Purpose |
|--------|---------------|---------|
| `_gpu_update_worker` | `config.gpu.update_frequency` (default 1s) | Reads GPU metrics from PyNVML, writes to `store.gpu_metrics` |
| `_cpu_update_worker` | `config.gpu.update_frequency` | Reads CPU/RAM/LM Studio process stats via psutil |
| `_models_update_worker` | 5s (exponential backoff to 60s on error) | Polls `/api/v1/models`; resets backoff on success |
| `_download_monitor_worker` | 2s | Polls `/tmp/ltu-download-state.json`; updates `store.download_progress`; notifies on completion |

**Theme override:** `search_themes()` is overridden to use `_MarkedThemeProvider` (defined at module level) which subclasses Textual's `ThemeProvider`, annotates the command list with `(current)` / `(default)` labels, and calls `self.app.notify()` on selection.

**Shutdown:** `on_shutdown()` (async) sets `_shutdown_event`, awaits `disconnect_from_server()`, calls `stop_gpu_monitoring()` and `stop_cpu_monitoring()`.

---

### `config.py` — Configuration

TOML config at `~/.config/lmstudio-tui/config.toml`. Dataclass hierarchy:

```
AppConfig
├── ServerConfig    [server]   host, port, timeout, retry, api_token_path, verify_ssl
├── GPUConfig       [gpu]      monitoring_enabled, update_frequency
│   └── AlertThresholds [alerts.temperature / alerts.vram]
├── ChatConfig      [chat]     system_prompt
└── lms_cli_path    [app]      optional override for lms binary path
```

`AppConfig.load(path)` uses `dacite.from_dict()` for safe deserialization with `strict=False` (extra keys ignored). `AppConfig.save(path)` uses `tomli_w`.

---

### `api/client.py` — LM Studio REST Client

`LMStudioClient` wraps httpx async. Key endpoints used:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/models` | List models with loaded status |
| `POST` | `/api/v1/models/load` | Load model (REST fallback only; payload: `model`, `context_length`, `flash_attention`) |
| `POST` | `/api/v1/models/unload` | Unload by `instance_id` |
| `POST` | `/v1/chat/completions` | OpenAI-compatible SSE streaming |

**Important:** The REST load API does **not** accept `gpu_offload` — it returns a 400 if passed. GPU offload is only available via `lms load --gpu`.

**API token auth:** `LMStudioClient.from_config()` reads a token from `~/.lmstudio/token` (or `config.server.api_token_path`) and sets `Authorization: Bearer <token>` if the file exists.

---

### `cli/lms_cli.py` — lms CLI Subprocess Wrapper

Provides the hybrid load path. `LmsCli` is instantiated and held by `RootStore`.

**Discovery order** (`LmsCli.discover()`):
1. Explicit `override_path` argument
2. `~/.lmstudio/bin/lms`
3. `which lms` on `$PATH`

**Key async methods:**

| Method | CLI command | Timeout |
|--------|-------------|---------|
| `load_model(model_key, context_length, gpu_offload_percent, ttl)` | `lms load <key> --context-length N --gpu F [--ttl N] [--host H:P]` | 120s |
| `estimate_memory(model_key, context_length, gpu_offload_percent)` | `lms load <key> --estimate-only --gpu F` | 30s |
| `start_download_detached(model_key)` | `lms get <model_key> -y` (detached Popen) | N/A |

**`gpu_offload_percent` encoding:** `-1` → `"max"`, `0` → `"off"`, `N` → `str(N/100)` (e.g. 75 → `"0.75"`).

**Download state files:**
- `/tmp/ltu-download-state.json` — `DownloadState` (pid, model_key, start_time, log_file)
- `/tmp/ltu-download.log` — raw `lms get` stderr; last 4 KB read for progress; ANSI codes stripped

**`_parse_estimate(output)`** parses `--estimate-only` stdout into `MemoryEstimate(gpu_memory_gb, total_memory_gb, feasibility)` using regex; returns zeros on parse failure rather than raising.

---

### `gpu/monitor.py` — GPU Monitoring

`GPUMonitor` uses PyNVML. `start()` calls `pynvml.nvmlInit()` and detects GPU count — returns `False` if no NVIDIA hardware or driver missing (graceful degradation). `get_metrics()` returns `list[GPUMetrics]`. No `stop()` method — shutdown via `pynvml.nvmlShutdown()` called in `store.stop_gpu_monitoring()`.

`GPUMetrics` fields: `gpu_id`, `name`, `utilization` (%), `vram_used` (MB), `vram_total` (MB), `temperature` (°C), `power_draw` (W).

---

### `cpu/monitor.py` — CPU Monitoring

`CPUMonitor` uses psutil. `start()` primes `psutil.cpu_percent(interval=None)` (first call is always 0.0; priming avoids a stale zero on the first real read). Returns `False` if psutil is unavailable.

`get_metrics()` returns `CPUMetrics`:
- `cpu_model` — from `/proc/cpuinfo` "model name" field, truncated to 27 chars
- `ram_free_gb` — `psutil.virtual_memory().available / 1024³`
- `ram_lmstudio_gb` — sum of RSS for processes where `"lmstudio"` is in name or `"/.lmstudio/"` is in cmdline
- `cpu_utilization` — `psutil.cpu_percent()`
- `cpu_lmstudio_pct` — sum of `p.cpu_percent()` for LM Studio processes

---

### `screens/` and `widgets/`

**Layout (main_screen.py):**
```
Vertical (main-content)
├── Container (logo-container)
│   └── AsciiLogo
└── Horizontal (content-row)
    ├── Vertical (left-column, 40%)
    │   ├── GPUPanel  (height: auto)
    │   ├── CPUPanel  (height: auto)
    │   └── ChatPanel (height: 1fr)
    └── ModelsPanel (60%, height: 100%)
```

**ChatPanel CSS notes (v0.4.2):** `border: none` must be set for **both** `ChatPanel Input` and `ChatPanel Input:focus`. Textual's `Input` component CSS applies `border: tall` in the focused state at higher specificity than a parent-selector rule — the explicit `:focus` override is required. Background tint (`$surface-lighten-1`) replaces the border as the focus indicator.

**ModelsPanel** contains three logical sub-sections:
1. Model DataTable (always visible)
2. LOAD CONFIGURATION frame (visible when model selected; GPU offload Select, Context Select, TTL Select, CALCULATE button, VRAM estimate display)
3. Download status frame (hidden by default; shown when `store.download_progress` is not None)

**model_browser_screen.py:** Full-screen modal. Calls `lms search <query>` via subprocess (sync), parses output into a list. Download via `LmsCli.start_download_detached()`. Dismisses back to main screen.

---

## Deployment — Live Server

| Item | Value |
|------|-------|
| Host | `192.168.101.21` |
| User | `sblanken` / password `101abn` |
| Sudo password | `101abn` |
| Install root | `/opt/lieutenant-underwood/` |
| Python venv | `/opt/lieutenant-underwood/venv/` |
| Launcher | `/usr/local/bin/lmstui` |
| Source (installed) | `/opt/lieutenant-underwood/venv/lib/python3.12/site-packages/lmstudio_tui/` |
| Source (master copy) | `/opt/lieutenant-underwood/src/lmstudio_tui/` |
| LM Studio binary | `~/.lmstudio/bin/lms` |
| LM Studio port | `1234` |
| GPUs | 4× NVIDIA RTX 3060 12 GB (48 GB total) |
| CPU | AMD EPYC 7282 16-Core |
| Models | Qwen3-Coder-30B, Ministral-3B/14B-Reasoning, Nomic-Embed-Text-v1.5 |

**Deploy pattern** (the package is installed non-editable, so `pip install --upgrade` is required after every source copy):

```bash
# 1. Rsync source to staging
sshpass -p '101abn' rsync -av --delete src/lmstudio_tui/ sblanken@192.168.101.21:/tmp/ltu-src/lmstudio_tui/

# 2. Install on server
sshpass -p '101abn' ssh sblanken@192.168.101.21 "echo '101abn' | sudo -S bash -c '
  cp -r /tmp/ltu-src/lmstudio_tui /opt/lieutenant-underwood/src/ &&
  /opt/lieutenant-underwood/venv/bin/pip install --upgrade /opt/lieutenant-underwood/ -q
'"
```

**If you only copy files without running pip install, the running code will NOT update** — Python loads from `site-packages`, not from `src/`.

---

## Test Suite

```bash
uv run --with "pytest>=7,pytest-asyncio>=0.21" pytest tests/ -v --tb=short
```

- **142 passed, 16 skipped** (skipped = hardware GPU tests requiring NVIDIA driver)
- `asyncio_mode = "auto"` in `pyproject.toml` — all async tests work without `@pytest.mark.asyncio`
- Tests use `unittest.mock` / `AsyncMock` extensively; no live server needed
- Key test files: `test_lms_cli.py`, `test_models_panel.py`, `test_store.py`, `test_race_condition.py`

---

## Known Patterns and Gotchas

1. **ReactiveVar vs Textual reactive:** Widget watchers must use `store.some_var.watch(callback)` in `on_mount()` and unregister in `on_unmount()`. Do NOT use Textual's `reactive` for store state — workers set values from outside the DOM.

2. **Textual CSS specificity:** Component `DEFAULT_CSS` (e.g. `Input:focus { border: tall }`) beats parent-selector rules (e.g. `ChatPanel Input { border: none }`). Always add explicit `:focus` overrides when suppressing widget focus styles.

3. **Non-editable pip install:** The live server uses `pip install` (non-editable). Always re-run `pip install --upgrade` after copying source. Stale `.pyc` files in `__pycache__` can also cause confusion — delete them if a change doesn't appear.

4. **`lms` CLI GPU arg encoding:** The `--gpu` flag accepts a float fraction (`0.75`), `"off"`, or `"max"`. Store uses integer percent internally (-1=max, 0=off, 1-100=percent). Conversion happens in `LmsCli._gpu_arg()`.

5. **`lms get` with `-y`:** Using `lms get <model> -y` suppresses the interactive GGUF picker. Do NOT add `--gguf` — it conflicts with exact artifact IDs that already include the quantization.

6. **Download log ANSI stripping:** `lms get` writes ANSI escape codes and carriage returns to stderr. `ANSI_ESCAPE` regex + `\r` → `\n` conversion in `lms_cli.py` normalises the output before showing the last non-empty line as progress.

7. **`lms --estimate-only` parses stderr, not stdout:** The output format is: `Model: ...`, `Estimated GPU Memory: X.XX GB`, `Estimated Total Memory: X.XX GB`, `Estimate: <text>`. Regex-based parser in `_parse_estimate()` returns zero-filled `MemoryEstimate` on failure rather than raising.

8. **Theme palette:** Textual 8.x has 20 built-in themes. `ThemeProvider` (in `textual.theme`) is the class to subclass. The `commands` property returns `list[tuple[str, Callable]]`. `search_themes()` on the App pushes a `CommandPalette(providers=[...])`.

9. **SSH connection drops:** `sshpass rsync` occasionally drops mid-session. Always test with a quick `sshpass ssh ... "echo ok"` before a large rsync, and chain commands with `&&` rather than separate calls.

---

## Planned Future Improvements

### 1. AMD GPU Support

**Goal:** GPU STATUS panel shows metrics for AMD GPUs (utilization, VRAM, temperature).

**Approach:**
- AMD GPUs expose metrics via `rocm-smi` CLI or the `amdsmi` Python library (ROCm 5.5+)
- Create `src/lmstudio_tui/gpu/amd_monitor.py` mirroring `GPUMonitor` interface: `start() -> bool`, `get_metrics() -> list[GPUMetrics]`
- `GPUMetrics` dataclass is already GPU-vendor-agnostic (no NVML-specific fields)
- `start_gpu_monitoring()` in `store.py` should try NVML first, then fall back to AMD monitor
- `amdsmi` may not be available on all systems — guard with `try/import` same as PyNVML
- Key challenge: `rocm-smi` output format varies by ROCm version; prefer `amdsmi` Python bindings when available
- Tests: mock `amdsmi` calls with `unittest.mock` following the same pattern as `test_gpu_monitor.py`

### 2. Additional Linux Distro Support

**Current assumption:** Ubuntu/Debian (uses `apt` in install.sh docs/comments).

**Goal:** Support Arch Linux, Rocky Linux, and Red Hat Enterprise Linux (RHEL).

**Changes needed in `scripts/install.sh`:**
- Detect distro via `/etc/os-release` (`ID` and `ID_LIKE` fields)
- Map package manager: `apt` (Debian/Ubuntu) → `pacman` (Arch) → `dnf` (RHEL/Rocky/Fedora)
- `python3-venv` package name differs: `python3-venv` (apt) vs included in `python3` (pacman) vs `python3` (dnf, venv is built-in on RHEL9+)
- `curl` and `git` package names are consistent across distros
- Consider adding a `--dry-run` flag to show what would be installed without executing
- RHEL/Rocky may require EPEL for some packages; document this in README prerequisites

**Changes needed in `README.md`:**
- Expand prerequisites table to list distro-specific package install commands
- Note ROCm requirement for AMD GPU support

### 3. Tokens Per Second (TPS) Performance Data

**Goal:** Display inference throughput in the TUI so operators can benchmark model performance under load.

**Where to show it:**
- **MODELS panel:** Add a `TPS` column to the model DataTable (show last measured value or `—` if not yet measured)
- **CHAT panel:** Show live TPS during active generation (e.g. `12.4 tok/s` updating in real time below the input)
- **Model detail screen:** Show peak and average TPS from the session

**How to calculate:**
- LM Studio's `/v1/chat/completions` SSE stream sends `data: {"choices": [{"delta": {"content": "..."}}]}` chunks
- Each chunk typically contains 1 token (occasionally more for special tokens)
- Track: `chunk_count` and `stream_start_time` in `ChatPanel._run_stream()`
- TPS = `chunk_count / (time.time() - stream_start_time)`
- Update display every N chunks (e.g. every 5) to avoid excessive redraws

**Implementation sketch:**
```python
# In chat_panel.py _run_stream():
chunk_count = 0
stream_start = time.time()
async for chunk in client.chat_completion(...):
    chunk_count += 1
    elapsed = time.time() - stream_start
    if elapsed > 0 and chunk_count % 5 == 0:
        tps = chunk_count / elapsed
        self._tps_widget.update(f"{tps:.1f} tok/s")
```

**Store integration:** Add `last_tps: ReactiveVar[Optional[float]]` to `RootStore` so the MODELS panel can display the last known TPS for a model independently of the chat panel.

**Caveat:** The `/v1/chat/completions` API does not currently expose server-side TPS in the SSE response headers or body (unlike some other servers). The client-side measurement includes network latency but is accurate enough for benchmarking purposes.

---

## Version History Summary

| Version | Date | Highlights |
|---------|------|------------|
| 0.4.2 | 2026-03-15 | Fix: chat input text hidden by `Input:focus` border override |
| 0.4.1 | 2026-03-15 | Fix: chat history `1fr`, input height 3, theme palette current/default markers |
| 0.4.0 | 2026-03-14 | CPU STATUS panel, download panel UX, PuTTY artifact fix, install.sh rewrite |
| 0.3.2 | 2026-03-10 | Detached download subprocess, live progress monitor, cancel support |
| 0.3.0 | 2026-03-05 | Hybrid lms CLI load path, GPU offload, TTL, real VRAM estimation, model browser |
| 0.2.0 | 2026-02-28 | API auth, system prompt, async disconnect, chat stream fixes, race condition fix |
| 0.1.0 | 2026-02-20 | Initial release |
