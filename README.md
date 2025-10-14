# TrayLocker

**Version 0.1.0-beta**

A Windows tray utility written in Rust that manages NumLock, CapsLock, and ScrollLock states.

## Features
- Three separate tray icons for NumLock, CapsLock, and ScrollLock
- Dynamic icon states (colored when on, gray when off)
- Individual "Force Always On" and "Force Always Off" controls for each lock key
- Settings persistence between application restarts
- Automatic startup option for Windows boot
- Clean, minimal GUI interface built with egui
- Background threads monitor and enforce key states every second
- Single instance enforcement
- Registry integration for auto-start

## Requirements
- Rust toolchain (install from https://rustup.rs/)
- Windows (this is Windows-specific due to registry and keyboard APIs)

## Installation
1. Clone the repository
2. Build the project: `cargo build --release`
3. Run the executable: `target/release/traylocker.exe`

## Usage
- Three tray icons will appear in the system tray
- Right-click any icon to access the Settings panel or Exit
- Use the Settings panel to toggle "Force Always On/Off" for each lock key and startup settings
- Click the "Visibility" button to open Windows Taskbar Settings for tray icon visibility
- Icons automatically change color based on lock key states
- Settings are automatically saved and restored
- Enable "Start at Boot" to automatically launch TrayLocker when Windows starts (uses Windows Registry)
- Only one instance can run at a time - attempting to start a second instance will exit gracefully
- Clean shutdown ensures all background threads are properly terminated when exiting

## Building
To build the release executable:
```bash
cargo build --release
```

This creates `traylocker.exe` in the `target/release/` folder. The executable includes all required icons embedded in the binary. Settings are automatically stored in the user's local app data folder (`%LOCALAPPDATA%\TrayLocker\settings.json`) and will persist across reboots.

## Migration from Python
This version is a complete rewrite in Rust for improved performance, reliability, and maintainability. The Python version has been archived.