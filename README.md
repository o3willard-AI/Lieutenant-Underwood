# Lieutenant-Underwood (LTU)
## LM Studio Terminal User Interface

**A Terminal UI for monitoring and managing an LM Studio headless inference server.**

Named in the tradition of military brevity: *Lieutenant Underwood* reports for duty as **LT U** — your **L**M-Studio **T**erminal **U**ser-interface.

```
╔════════════════════════════════════════════════════════╗
║  Lieutenant-Underwood v0.9.6                           ║
║  LM Studio Terminal User Interface                     ║
╚════════════════════════════════════════════════════════╝
```

---

## Features

- **GPU STATUS** — Real-time metrics for all NVIDIA GPUs: utilization %, VRAM used/total, temperature, power draw
- **CPU STATUS** — Live system overview: CPU model, free RAM, LM Studio RAM usage, CPU utilization, LM Studio CPU %
- **MODELS Panel** — Browse and select models; the table shows Status, **Ctx In/Out** (configured → actual context window), Size, and Model Name. Press `Enter` to open the detail screen for load configuration (GPU offload %, context length, TTL auto-unload) and VRAM estimates. The detail screen also shows the actual quantization and context window currently being served by LM Studio so you can spot any override immediately
- **PERFORMANCE Panel** — Real-time inference metrics: TPS (now/peak/avg), TTFT avg (in seconds), total requests, and total tokens out. Tracks both TUI-initiated chat *and* external API clients via passive network sniffing
- **CHAT Panel** — Send messages to a loaded model with live streaming response; slash commands for model switching, import, and calibration
- **Model Browser** — Two-step search and download from Hugging Face: browse repos by downloads/stars/date, then select a specific quantization variant (Q4_K_M, Q8_0, etc.) with file sizes shown. Downloads stream directly from huggingface.co — works for any public GGUF model, not just the LM Studio catalog
- **Download Monitor** — Live progress display with bytes received, speed (MB/s), and cancel support. Downloaded files are placed in `~/.lmstudio/models/` where LM Studio picks them up automatically
- **Delete Model** — Press `r` to open a two-step deletion screen that scans `~/.lmstudio/models/` with sizes and loaded-model safety checks
- **Hybrid Load Path** — Uses the `lms` CLI for model loading when available (unlocks GPU layer offload and TTL); falls back to REST API automatically

---

## Screenshot

![Lieutenant-Underwood — live on a 4× RTX 3060 server](screenshots/dashboard.png)

*Live dashboard: 4× NVIDIA RTX 3060 (48 GB VRAM total) · Qwen3 Coder 30B loaded · lms CLI active*

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Linux** | Ubuntu 20.04+ recommended (tested on Ubuntu 24.04) |
| **Python 3.9+** | With `python3-venv` (`sudo apt install python3-venv`) |
| **git** | For cloning the installer and source (avoids CDN caching issues) |
| **libcap2-bin** | For `setcap` (grants `CAP_NET_RAW` to tcpdump); `sudo apt install libcap2-bin` |
| **tcpdump** | For the passive network sniffer; `sudo apt install tcpdump` |
| **LM Studio** | Installed and accessible; the `lms` CLI at `~/.lmstudio/bin/lms` |
| **NVIDIA GPU + drivers** | Optional — GPU STATUS panel requires PyNVML/NVIDIA drivers |

All Python dependencies (Textual, httpx, psutil, pynvml, tomli, dacite, etc.) are installed automatically by the installer.

---

## Installation

### Fresh Install

```bash
git clone --depth 1 https://github.com/o3willard-AI/Lieutenant-Underwood.git /tmp/ltu
sudo bash /tmp/ltu/scripts/install.sh
rm -rf /tmp/ltu
```

The installer will:
1. Check Python version and `venv` availability
2. Download the latest source from the `master` branch on GitHub
3. Create `/opt/lieutenant-underwood/` with an isolated Python venv
4. Install all dependencies into the venv
5. Grant `CAP_NET_RAW` to the system `tcpdump` binary so the network sniffer can capture traffic
6. Create the `/usr/local/bin/lmstui` launcher
7. Write a default config to `~/.config/lmstudio-tui/config.toml`

After installation, launch with:

```bash
lmstui
```

> **Note on network sniffing:** Step 5 runs `setcap cap_net_raw+eip $(which tcpdump)`. The sniffer spawns `tcpdump` as a subprocess — a separate C process with its own memory space, so it has no GIL impact on Python and negligible effect on host network throughput. If `libcap2-bin` or `tcpdump` is not installed, the installer prints a warning and continues; all other features remain functional, and GPU-utilization-based TPS estimation acts as a fallback.

---

### Upgrade

```bash
git clone --depth 1 https://github.com/o3willard-AI/Lieutenant-Underwood.git /tmp/ltu
sudo bash /tmp/ltu/scripts/install.sh --upgrade
rm -rf /tmp/ltu
```

This will:
- Stop any running `lmstui` process
- Download the latest source from the `master` branch on GitHub
- Replace the application files in `/opt/lieutenant-underwood/src/`
- Run `pip install --upgrade` inside the venv
- Re-apply `setcap` to tcpdump in case it was updated
- Recreate the `/usr/local/bin/lmstui` launcher

Your config at `~/.config/lmstudio-tui/config.toml` is **not touched**.

---

### Uninstall

```bash
git clone --depth 1 https://github.com/o3willard-AI/Lieutenant-Underwood.git /tmp/ltu
sudo bash /tmp/ltu/scripts/install.sh --uninstall
rm -rf /tmp/ltu
```

If the installer placed an `uninstall.sh` in `/opt/lieutenant-underwood/` you can also run it directly:

```bash
sudo bash /opt/lieutenant-underwood/uninstall.sh
```

Either method removes `/opt/lieutenant-underwood/` and `/usr/local/bin/lmstui`.

User config at `~/.config/lmstudio-tui/` is **preserved**. Remove it manually if desired:

```bash
rm -rf ~/.config/lmstudio-tui/
```

---

## Usage

```bash
# Launch (LM Studio must be running or you will be prompted)
lmstui

# Options
lmstui --host 192.168.1.10   # Connect to remote LM Studio
lmstui --port 1235            # Override port (default: auto-detect)
lmstui --debug                # Enable debug logging
lmstui --version              # Show version
```

On launch, the TUI checks Python version, verifies LM Studio is installed, then auto-detects which port (1234–1240) LM Studio is responding on. If LM Studio is not running, you will be asked whether to start it.

---

## Layout

All panels stack in a single full-width column:

```
┌──────────────────────────────────────────────────────┐
│  ASCII Logo / Banner                                 │
├──────────────────────────────────────────────────────┤
│  💻 GPU STATUS                                       │
│  utilization % · VRAM used/total · temp · power      │
├──────────────────────────────────────────────────────┤
│  🖥  CPU STATUS                                      │
│  model · free RAM · LM Studio RAM · CPU % · LMS CPU% │
├──────────────────────────────────────────────────────┤
│  🤖 MODELS                                           │
│  Status · Ctx In/Out · Size · Model Name             │
│  (Enter = detail screen, d = HF browser, r = delete) │
├──────────────────────────────────────────────────────┤
│  ⚡ PERFORMANCE                                      │
│  TPS now · TPS peak · TPS avg · TTFT avg             │
│  Requests · Tokens out                               │
├──────────────────────────────────────────────────────┤
│  💬 CHAT                                             │
│  streaming chat · slash commands                     │
└──────────────────────────────────────────────────────┘
```

---

## Keybindings

### Global

| Key | Action |
|-----|--------|
| `q` | Quit |
| `?` | Show help |
| `Tab` | Focus next panel |
| `d` | Open model browser (Hugging Face search & download) |
| `r` | Open delete model screen |

### Models Panel (when focused)

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate model list |
| `Enter` | Open model detail screen (configure, load, unload) |
| `d` | Open model browser |
| `r` | Open delete model screen |

### Model Detail Screen

Load configuration lives here, not on the main panel. For loaded models, the screen also shows the **actual** context window and quantization currently reported by LM Studio — any discrepancy from the configured value is highlighted in orange.

| Control | Description |
|---------|-------------|
| **Quantization** | (info row) Quantization type reported by LM Studio API |
| **Loaded ctx** | (info row) Actual context window served; orange warning if LM Studio overrode the configured value |
| **GPU offload** | (info row) Actual GPU layer fraction, when reported by the API |
| **GPU Layer Offload** | `Max` (auto), `75%`, `50%`, `25%`, `CPU only` |
| **Context Length** | 8K–262K (auto-estimates VRAM for each option) |
| **Auto-Unload (TTL)** | Off, 1 min, 5 min, 30 min, 1 hour |
| **Load** button | Loads the model with the selected settings |
| **Unload** button | Unloads the currently loaded model |

VRAM estimates (Q4_0 low / Q8_0 mid / F16 high) update instantly as you change settings — no button required.

After each load, the actual context window LM Studio used is compared against what was requested, and any delta is logged to `app.log` and shown as a toast notification.

### Model Browser

| Key / Button | Action |
|---|---|
| `↑` / `↓` | Navigate repo list or file list |
| `⬇ Select File` | Open quantization picker for selected repo |
| `Enter` | Same as Select File (in browse mode) |
| `⬇ Download` | Start download of selected `.gguf` file |
| `← Back` / `Esc` | Return to repo list from file picker |
| `Close` / `Esc` | Close the browser |

### Chat Panel

| Command | Action |
|---------|--------|
| (type message) | Send to loaded model with streaming response |
| `/switch <model_id>` | Set active model for chat |
| `/add <local_path>` | Import a local model file into LM Studio |
| `/clear` | Clear chat history |
| `/cal` | Run calibration prompt (~5 k tokens) to prime the GPU/TPS estimator |
| `/help` | Show available commands |

### Theme Switcher

| Key | Action |
|-----|--------|
| `Ctrl+P` | Open command palette |

Type **Theme** in the palette then select from the full list. The current theme is marked **(current)** and the built-in default is marked **(default)**. A toast notification confirms every change. 20 themes are available including `nord`, `dracula`, `gruvbox`, `catppuccin-mocha`, `tokyo-night`, and more.

---

## MODELS Panel — Ctx In/Out Column

The **Ctx In/Out** column shows the configured context (what the TUI will request) and the actual context window LM Studio is serving, side-by-side:

| Display | Meaning |
|---------|---------|
| `8K/-` | Model is not loaded; TUI is configured to request 8K tokens |
| `64K/64K` | Loaded; LM Studio served exactly what was requested |
| `128K/64K ⚠` | Loaded; TUI requested 128K but LM Studio only loaded 64K |

The `⚠` flag and an orange highlight in the detail screen indicate that LM Studio overrode the requested context window — useful for diagnosing whether context mismatches originate in the TUI's VRAM estimates or in LM Studio's runtime limits.

Context values are shown in binary kibibytes (1K = 1024 tokens).

---

## PERFORMANCE Panel

The PERFORMANCE panel shows six inference metrics that update every second:

| Metric | Description |
|--------|-------------|
| **TPS (now)** | Rolling tokens/sec over the last 5 seconds. Shows `~` prefix when value is GPU-estimated rather than exact |
| **TPS (peak)** | Highest tokens/sec burst seen this session |
| **TPS (avg)** | Session-wide average tokens/sec (denominator is active-inference time only, not idle time) |
| **TTFT avg** | Average time-to-first-token in **seconds**, over the last 3 completed requests (e.g. `2.4s (last 3)`) |
| **Requests** | Total completed inference requests since the TUI started |
| **Tokens out** | Total output tokens generated this session |

All counters reset when the TUI restarts.

### How external inference is tracked

The TUI can only directly instrument requests it sends itself. Two mechanisms cover external API clients:

1. **Passive network sniffer** (primary) — `tcpdump` runs as a child process watching all interfaces for HTTP traffic on the LM Studio port. Each SSE `data: {` line in server→client output counts as one output token; TTFT is measured from the first `POST /v1/chat/completions` line to the first `data: {`; the request counter increments on `data: [DONE]`. Uses kernel BPF filtering so only matching packets reach Python — negligible impact on host network throughput. Requires `CAP_NET_RAW` on the `tcpdump` binary (granted automatically by the installer).

2. **GPU-utilization estimation** (fallback) — if the sniffer is unavailable, the GPU worker maintains a calibration ratio (tokens/sec ÷ GPU%) derived from observed TUI chat sessions via EMA. When the GPU exceeds 20 % utilization with no active TUI request, TPS (now) is estimated as `ratio × current GPU%` and marked with a `~` prefix. Run `/cal` in the CHAT panel to build the ratio quickly with a sustained ~5 k-token response.

---

## Context Window Verification & Delta Logging

Every time you load a model through the TUI, the actual context window reported by LM Studio is compared against what was requested. The delta is written to `app.log`:

```
INFO  Load request [model/id]: context=131072, gpu_offload=max
INFO  Load delta [model/id]: context req=131072 actual=65536 delta=-65536 (-50.0%); gpu_offload req=max actual=not reported by API
WARNING  Context mismatch [model/id]: LM Studio loaded 65536 tokens vs requested 131072 (under by 65,536 tokens / 50.0%)
```

This provides hard data on whether context overrides originate inside LM Studio (runtime VRAM limits) or in the TUI's pre-load VRAM estimate calculation.

---

## Configuration

Config file: `~/.config/lmstudio-tui/config.toml`

```toml
[server]
host = "localhost"      # LM Studio server hostname or IP
port = 1234             # Override port (default: auto-detect 1234–1240)
timeout = 10.0          # HTTP request timeout in seconds
retry = true            # Retry on transient errors
verify_ssl = true       # Verify SSL certificates (for HTTPS servers)
# api_token_path = "~/.lmstudio/token"  # Path to API auth token file

[gpu]
monitoring_enabled = true
update_frequency = 1.0  # Seconds between GPU/CPU metric polls

[chat]
system_prompt = "You are a helpful assistant."

[app]
# lms_cli_path = "/custom/path/to/lms"  # Override lms binary location
```

### lms CLI Auto-Detection

Lieutenant-Underwood looks for the `lms` binary in this order:
1. `lms_cli_path` from `[app]` section of config (if set)
2. `~/.lmstudio/bin/lms` (standard LM Studio install location)
3. `lms` on `$PATH` (via `which lms`)

If `lms` is found, the MODELS panel shows **⚡ lms CLI: active** and full GPU offload / TTL support is enabled. If not found, a warning is shown and model loading falls back to the REST API (no GPU offload or TTL).

---

## Development

```bash
# Clone
git clone https://github.com/o3willard-AI/Lieutenant-Underwood
cd Lieutenant-Underwood

# Set up dev environment (using uv)
uv sync

# Run tests
uv run --with "pytest>=7,pytest-asyncio>=0.21" pytest tests/ -v --tb=short

# Run the TUI in development
uv run python -m lmstudio_tui.launcher
```

### Project Structure

```
src/lmstudio_tui/
├── __init__.py          # Version
├── app.py               # Textual App root, background workers
├── config.py            # AppConfig dataclass + TOML load/save
├── downloader.py        # Direct HF streaming downloader (bypasses lms get)
├── launcher.py          # lmstui entry point with pre-flight checks
├── store.py             # Singleton RootStore with ReactiveVar state
├── utils.py             # format_size(), format_context_length(), extract_quantization()
├── api/
│   └── client.py        # httpx async client for LM Studio REST API
├── cli/
│   └── lms_cli.py       # lms subprocess wrapper (load and estimate only)
├── cpu/
│   └── monitor.py       # CPUMonitor using psutil
├── gpu/
│   └── monitor.py       # GPUMonitor using PyNVML
├── network/
│   └── http_sniffer.py  # Passive tcpdump subprocess sniffer for external inference
├── screens/
│   ├── main_screen.py          # Main dashboard layout (single column)
│   ├── model_detail_screen.py  # Per-model detail, actual config display, load/unload
│   ├── model_browser_screen.py # Hugging Face model browser (browse → file picker)
│   └── delete_model_screen.py  # Filesystem model deletion with two-step confirm
└── widgets/
    ├── ascii_logo.py        # Banner logo
    ├── chat_panel.py        # Streaming chat interface + slash commands
    ├── cpu_panel.py         # CPU/RAM status table
    ├── gpu_panel.py         # GPU metrics table
    ├── models_panel.py      # Model list with Ctx In/Out column + download status
    └── performance_panel.py # Real-time inference metrics (6 counters)
```

---

## Hardware Tested

- **Server:** Ubuntu 24.04, LM Studio headless
- **GPUs:** 4× NVIDIA GeForce RTX 3060 12GB (48 GB total VRAM)
- **Models tested:** Qwen3-Coder-30B, Ministral-3B/14B, Nomic-Embed-Text

---

## Logs

Application logs are written to `~/.local/share/lmstudio-tui/app.log` with automatic rotation (5 MB max, 3 backups). Enable verbose logging with `lmstui --debug`.

Load delta entries are written at `INFO` level on every model load; mismatches additionally emit a `WARNING` line for easy `grep`:

```bash
grep "Context mismatch" ~/.local/share/lmstudio-tui/app.log
```

---

## License

MIT — See [LICENSE](LICENSE) for details.

---

**LTU standing by.** 🤖⚡
