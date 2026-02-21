# LM Studio TUI

Terminal UI for LM Studio headless server monitoring and management.

## Features

- Real-time GPU monitoring with NVIDIA PyNVML
- Model management and downloading
- Multi-agent LAN discovery via mDNS
- Alert thresholds for temperature and VRAM
- Customizable keyboard shortcuts

## Installation

```bash
make install
```

## Usage

```bash
lmstudio-tui
# or
make run
```

## Development

```bash
make test      # Run tests
make lint      # Check code style
make format    # Format code
```

## Configuration

See `config/example.toml` for a complete configuration example.

## License

MIT
