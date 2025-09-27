# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-beta] - 2025-09-27

### Added
- Initial beta release of TrayLocker
- System tray icons for NumLock, CapsLock, and ScrollLock with dynamic state indication
- Individual "Force Always On" controls for each lock key
- Settings persistence using JSON storage in user's local app data
- Windows startup integration via registry with automatic cleanup of old entries
- Single-instance enforcement to prevent conflicts
- Memory-safe design with proper thread management and resource cleanup
- Settings validation and repair for corrupted configuration files
- Comprehensive documentation and agent guidelines

### Technical Details
- Built with Python using pystray, pillow, and pywin32 libraries
- Cross-platform executable building with PyInstaller
- Registry consistency checking and automatic repair
- Thread-safe settings management with debounced saving
- Clean shutdown handling for all background processes