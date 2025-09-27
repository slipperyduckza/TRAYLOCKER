# Agent Guidelines for TrayLocker

**Version 0.1.0-beta**

## Build Commands
- Install: `pip install pystray pillow pywin32`
- Build exe: `pyinstaller --onefile --windowed --icon icon.png --add-data "icon_*_*.png;." --exclude-module unittest --exclude-module test traylocker.py`

## Test Commands
- No tests defined - add to `test_traylocker.py`
- Run single test: `python -m pytest test_traylocker.py::TestClass::test_method -v`

## Lint Commands
- Lint: `python -m flake8 traylocker.py`
- Format: `python -m black traylocker.py`

## Code Style Guidelines
- **Imports**: Standard library → third-party → local. One per line, absolute imports.
- **Naming**: snake_case functions/variables (e.g., `keep_numlock`), UPPER_CASE constants (e.g., `VK_NUMLOCK`)
- **Formatting**: 4 spaces indent, 88 char lines, double quotes for strings
- **Types**: No type hints currently used
- **Error Handling**: try/except for system ops, pass on expected errors. Docstrings for functions, inline comments for complex logic
- **Thread/Resource Mgmt**: shutdown_event for clean termination, track threads in running_threads, always close registry keys, @lru_cache, proper cleanup
- **Windows-specific**: win32api integration, single-instance enforcement, automatic registry cleanup