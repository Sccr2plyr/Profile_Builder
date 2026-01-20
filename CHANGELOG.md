# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-01-20

### Added
- **Test Blocks Feature**: Sequential execution of multiple independent waveform blocks
  - Each block has its own schedule and cycle count
  - Blocks execute one after another in order
  - Add/remove/reorder blocks in the UI
  - Editable block names and cycles
- **Modular Architecture**: Separated codebase into focused modules
  - `models.py`: Data structures (Profile, Block, PositionConfig, ScheduledEvent)
  - `waveform_engine.py`: Waveform generation algorithms
  - `pico_serial.py`: Serial communication with Pico
  - `utils.py`: Helper functions
  - `config.py`: Configuration constants
- **Scrollable Left Panel**: All controls remain accessible regardless of profile length
- **Block Boundaries in Preview**: Visual indicators showing where blocks transition
- **Comprehensive Documentation**: Extensive docstrings throughout codebase
- **Backward Compatibility**: Load old single-schedule profiles automatically

### Changed
- Profile structure now uses `blocks` instead of single `scheduled_events` + `cycles`
- Preview summary shows block count and total cycles across all blocks
- Waveform generation processes blocks sequentially with time offsets

### Fixed
- Schedule row unpacking errors when switching between blocks
- PanedWindow compatibility with ScrolledFrame

## [1.0.0] - 2025-XX-XX

### Added
- Initial release with basic waveform profile builder
- Single schedule with cycle count
- Multi-position configuration
- Pico serial communication
- Real-time waveform preview
- Save/load JSON profiles
