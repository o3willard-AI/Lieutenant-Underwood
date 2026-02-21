# Lieutenant-Underwood (LTU)
## LM-Studio Terminal User-interface

**A Terminal UI for LM Studio headless server monitoring and management.**

Named in the tradition of military brevity: *Lieutenant Underwood* reports for duty as **LT U** — your **L**M-Studio **T**erminal **U**ser-interface.

---

## Features

- **Real-time GPU Monitoring** — Live metrics for all NVIDIA GPUs (utilization, VRAM, temperature, power)
- **Model Management Panel** — Browse, load, and unload models with visual status indicators
- **Reactive State Management** — Custom ReactiveVar pattern for automatic UI updates
- **Multi-agent LAN Discovery** — Auto-discover LM Studio servers on local network (mDNS/Zeroconf)
- **Alert Thresholds** — Configurable warnings for GPU temperature and VRAM usage
- **Customizable Keybindings** — Vim-like shortcuts for power users

---

## Quick Start

```bash
# Install (development mode)
make install

# Run the TUI
lmstudio-tui
# or
make run
```

---

## Architecture

Built with **atomic scaffolding** using a hybrid agent orchestration strategy:

| Atoms 01-06 (Ralph-Loop) | Atoms 07-08 (4-Role) |
|--------------------------|----------------------|
| Project structure | Reactive state store |
| Config loader | GPU panel with live updates |
| API client | |
| GPU monitor | |
| App skeleton | |
| ASCII logo | |

**101 tests passing** on real hardware (4x NVIDIA RTX 3060)

---

## Development

```bash
# Run all tests
make test

# Lint check (ruff + black)
make lint

# Format code
make format

# Type check
make typecheck
```

---

## Keybindings

### Global

| Key | Action |
|-----|--------|
| `q` | Quit application |
| `r` | Refresh all data |
| `?` | Show help |
| `Tab` | Focus next panel |

### Models Panel

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate model list |
| `Enter` | Open model details |
| `l` | Load selected model |
| `u` | Unload selected model |
| `r` | Refresh models list |

---

## Configuration

See `config/example.toml` for complete configuration options:

```toml
[server]
host = "localhost"
port = 1234

[gpu]
monitoring_enabled = true
update_frequency = 1.0

[alerts.temperature]
warning = 80
critical = 90

[alerts.vram]
warning = 95
critical = 98
```

---

## Agent Orchestration Playbook

This project was built using documented multi-agent patterns. See the [Agent Orchestration Playbook](docs/AGENT_ORCHESTRATION_PLAYBOOK.md) for:

- Ralph-Loop pattern (simple atoms)
- 4-Role Sequential pattern (complex integration)
- Build commands and quality gates
- Testing patterns and lessons learned

---

## Hardware Tested

- **GPUs:** 4x NVIDIA GeForce RTX 3060 (12GB)
- **Server:** LM Studio headless on Ubuntu 24.04
- **Metrics:** Real-time temperature, utilization, VRAM, power draw

---

## License

MIT — See [LICENSE](LICENSE) for details.

---

**LTU standing by.** 🤖⚡
