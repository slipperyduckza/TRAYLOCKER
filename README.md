# TrayLocker

**Version 0.1.0-beta**

A Windows tray utility that manages NumLock, CapsLock, and ScrollLock states.

## Features
- Three separate tray icons for NumLock, CapsLock, and ScrollLock
- Dynamic icon states (colored when on, gray when off)
- Individual "Force Always On" controls for each lock key
- Settings persistence between application restarts
- Automatic startup option for Windows boot
- Clean, minimal interface

## Requirements
- Python 3.x
- pystray
- pillow
- pywin32

## Installation
1. Install dependencies: `pip install pystray pillow pywin32`
2. Run the script: `python traylocker.py`

## Usage
- Three tray icons will appear in the system tray
- Right-click any icon to access the Settings panel
- Use the Settings panel to toggle "Force Always On" for each lock key and startup settings
- Icons automatically change color based on lock key states
- Settings are automatically saved and restored
- Enable "Start at Bootup" to automatically launch TrayLocker when Windows starts (uses Windows Registry)
- Only one instance can run at a time - attempting to start a second instance will exit gracefully
- Startup validation ensures registry and settings file consistency
- Automatic cleanup of old registry entries prevents conflicts during upgrades
- Clean shutdown ensures all background processes are properly terminated when exiting

## Building
To create a standalone executable with embedded icons and application icon:
```bash
pyinstaller --onefile --windowed --icon icon.png --add-data "icon_*_*.png;." --exclude-module unittest --exclude-module test traylocker.py
```

This creates `traylocker.exe` in the `dist/` folder. The executable includes all required icons and uses `icon.png` as the application icon. Settings are automatically stored in the user's local app data folder (`%LOCALAPPDATA%\TrayLocker\settings.json`) and will persist across reboots.