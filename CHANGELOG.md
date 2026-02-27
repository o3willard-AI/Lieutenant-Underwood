# Changelog

All notable changes to the LMStudio TUI project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

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
