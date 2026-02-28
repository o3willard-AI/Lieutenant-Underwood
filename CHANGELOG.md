# Changelog

All notable changes to the LMStudio TUI project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **UAT Session 5:** Chat timeout, GPU headers, config layout, VRAM estimator
  - **Fix 1:** Chat timeout and error handling with GPU-based health monitoring
    - Added 30-second timeout for stalled streams (checks GPU activity)
    - Graceful cancellation with user-friendly error messages
    - Prevents "Thinking..." lockups with automatic recovery
  - **Fix 2:** GPU panel DataTable headers now render correctly
    - Headers (GPU, Model, VRAM Total, etc.) visible on app startup
    - Fixed initialization timing in `on_mount()`
  - **Fix 3:** Config menu compact vertical layout
    - Selectors now directly under their labels
    - Added descriptive text for each config option
    - Reduced wasted horizontal space
  - **Fix 5:** VRAM/RAM estimator row added to config panel
    - Real-time calculation based on model size, context, offload %, KV quant
    - Color-coded: green (fits), yellow (tight), red (won't fit)
    - Updates when selection or GPU metrics change

- **C2-race-condition:** Eliminated TOCTOU race condition in gpu_monitor access
  - Applied atomic reference capture pattern in `src/lmstudio_tui/app.py`
  - Captures `gpu_monitor` reference locally before checking/using it
  - Prevents crashes during concurrent shutdown scenarios
  - Added 4 new unit tests for race condition scenarios
  - Commit: `a26c850`

## [0.1.0] - 2026-02-20

### Added

- Initial project structure
- Basic TUI interface with Textual
- GPU monitoring widget
- Configuration management
- API client for LM Studio

### Notes

- Pre-existing test failures (9 total) unrelated to recent changes:
  - Config tests: Port mismatch (1234 vs 1235)
  - API client tests: URL path mismatches
  - Store tests: Missing `gpu_monitor` property

---

## Template for Future Entries

### Added
- New features

### Changed
- Changes in existing functionality

### Deprecated
- Soon-to-be removed features

### Removed
- Now removed features

### Fixed
- Bug fixes

### Security
- Security improvements
