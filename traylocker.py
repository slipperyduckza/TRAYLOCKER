"""
TrayLocker - A Windows system tray application that manages lock key states.

Version: 0.1.0-beta

This application creates system tray icons for NumLock, CapsLock, and ScrollLock
that can automatically maintain these keys in a desired state. Users can configure
each key to be "forced on" through a settings window, and the application ensures
only one instance runs at a time.

Key Features:
- Automatic lock key state management (force keys to stay on/off)
- Real-time system tray icons showing current lock key states
- Persistent settings stored in user's local app data
- Windows startup integration via registry with automatic cleanup
- Memory-safe design with proper resource cleanup and thread management
- Single-instance enforcement to prevent conflicts

Technical Details:
- Uses pystray for system tray integration
- Leverages win32api for keyboard state monitoring and control
- Implements multi-threading for responsive UI and background monitoring
- Stores settings in JSON format in %LOCALAPPDATA%/TrayLocker/
- Automatically cleans up old registry entries on startup
"""

import pystray
from PIL import Image
import win32api
import win32con
import win32event
import time
import threading
import sys
import os
import json
import winreg
import signal
from functools import lru_cache
import tkinter as tk
from tkinter import ttk

# Application version information
__version__ = "0.1.0-beta"
__version_info__ = (0, 1, 0, "beta")

# Settings file path - store in local app data for consistency across reboots
SETTINGS_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'TrayLocker')
os.makedirs(SETTINGS_DIR, exist_ok=True)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'settings.json')

class LockKeyManager:
    """
    Central manager for lock key settings and persistence.

    This class serves as the core data model and persistence layer for TrayLocker.
    It manages all settings related to lock key behavior and Windows integration.

    Responsibilities:
    - Maintains current settings for each lock key (NumLock, CapsLock, ScrollLock)
    - Handles loading/saving settings to JSON file in user's app data directory
    - Manages Windows registry integration for automatic startup
    - Validates and repairs corrupted settings files
    - Provides thread-safe access to settings data

    Each lock key configuration includes:
    - vk: Virtual key code used by Windows API (e.g., win32con.VK_NUMLOCK)
    - force_on: Boolean flag indicating if this key should be automatically kept on
    - icon_base: Base filename for icon images (e.g., 'icon_numlock')
    - name: Human-readable display name for UI elements
    """

    def __init__(self):
        # Define all supported lock keys with their properties
        # vk = Virtual Key code used by Windows API
        # force_on = True means we'll automatically turn this key on if it gets turned off
        # icon_base = filename prefix for the icon images
        # name = human-readable name for menus and dialogs
        self.keys = {
            'numlock': {'vk': win32con.VK_NUMLOCK, 'force_on': False, 'icon_base': 'icon_numlock', 'name': 'NumLock'},
            'capslock': {'vk': win32con.VK_CAPITAL, 'force_on': False, 'icon_base': 'icon_capslock', 'name': 'CapsLock'},
            'scrollock': {'vk': win32con.VK_SCROLL, 'force_on': False, 'icon_base': 'icon_scrollock', 'name': 'ScrollLock'}
        }

        # Whether TrayLocker should start automatically when Windows boots
        self.startup_enabled = False

        # Timer for debounced settings saving (prevents excessive disk writes)
        self._save_timer = None

        # Load existing settings from file and validate them
        self.load_settings()

    def cleanup_old_registry_entries(self):
        """
        Clean up old or incorrect registry entries for TrayLocker startup.

        This function removes any existing TrayLocker registry entries that may
        have been created by previous versions or different installation paths.
        This prevents conflicts during upgrades or when the application is moved.

        After cleanup, the correct registry entry is added if startup is enabled.
        """
        try:
            # Open the registry key for startup programs
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_ALL_ACCESS)

            # Get all startup entries to find TrayLocker-related ones
            entries_to_remove = []
            try:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        # Look for any entries containing "TrayLocker" (case-insensitive)
                        if "traylocker" in name.lower():
                            entries_to_remove.append(name)
                        i += 1
                    except OSError:
                        # No more values
                        break
            except OSError:
                pass

            # Remove all found TrayLocker entries
            for entry_name in entries_to_remove:
                try:
                    winreg.DeleteValue(key, entry_name)
                    print(f"Removed old registry entry: {entry_name}")
                except OSError as e:
                    print(f"Warning: Could not remove registry entry {entry_name}: {e}")

            winreg.CloseKey(key)

            # Now add the correct entry if startup is enabled
            if self.startup_enabled:
                self.enable_startup()
                print("Added correct registry entry for current application")

        except (OSError, WindowsError) as e:
            print(f"Warning: Could not clean up registry entries: {e}")

    def check_registry_consistency(self):
        """
        Ensure Windows registry startup setting matches our JSON settings.

        This prevents inconsistencies where someone manually edits the registry
        or the settings file gets corrupted. We treat the JSON file as the
        "source of truth" and update the registry to match it.

        The registry key is: HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
        """
        try:
            # Open the Windows registry key that controls startup programs
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_READ)
            try:
                # Check if TrayLocker is listed in startup programs
                registry_value = winreg.QueryValueEx(key, "TrayLocker")[0]
                # Consider it "enabled" if there's a non-empty value
                registry_enabled = registry_value is not None and len(registry_value.strip()) > 0
            except FileNotFoundError:
                # TrayLocker is not in startup registry
                registry_enabled = False
            finally:
                # Always close registry keys to prevent resource leaks
                winreg.CloseKey(key)

            # If registry and JSON settings don't match, fix the registry
            if registry_enabled != self.startup_enabled:
                print(f"Registry/JSON mismatch detected. Registry: {registry_enabled}, JSON: {self.startup_enabled}")
                # JSON is source of truth - update registry to match
                if self.startup_enabled:
                    self.enable_startup()
                else:
                    self.disable_startup()
                print("Registry updated to match JSON settings")

        except (OSError, WindowsError) as e:
            # Registry access can fail due to permissions or system issues
            print(f"Warning: Could not check registry consistency: {e}")

    def validate_settings(self):
        """
        Validate settings file and repair if corrupted or incomplete.

        This method ensures the settings file is always in a valid state:
        1. Checks that all required settings keys exist
        2. Adds missing keys with default values
        3. Handles corrupted JSON by creating a backup and resetting
        4. Creates default settings file if none exists

        This prevents the app from crashing due to missing or invalid settings.
        """
        try:
            if os.path.exists(SETTINGS_FILE):
                # Load existing settings file
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)

                # Check that all required settings exist (one for each lock key + startup)
                needs_update = False
                for key_name in self.keys.keys():
                    key = f'force_{key_name}_always_on'
                    if key not in settings:
                        settings[key] = False  # Default: don't force on
                        needs_update = True

                # Check startup setting exists
                if 'start_at_bootup' not in settings:
                    settings['start_at_bootup'] = False  # Default: don't start at boot
                    needs_update = True

                # Save updated settings if we added missing keys
                if needs_update:
                    with open(SETTINGS_FILE, 'w') as f:
                        json.dump(settings, f, indent=2)
                    print("Settings file updated with missing keys")

                # Load the validated settings into our object
                for key_name, key_data in self.keys.items():
                    key_data['force_on'] = settings.get(f'force_{key_name}_always_on', False)
                self.startup_enabled = settings.get('start_at_bootup', False)

            else:
                # No settings file exists - create default one
                default_settings = {f'force_{key_name}_always_on': False
                                  for key_name in self.keys.keys()}
                default_settings['start_at_bootup'] = False
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(default_settings, f, indent=2)
                print("Default settings file created")

        except (json.JSONDecodeError, IOError) as e:
            # Settings file is corrupted or unreadable
            print(f"Warning: Could not validate settings file: {e}")

            # Try to create a backup of the corrupted file
            if os.path.exists(SETTINGS_FILE):
                backup_file = SETTINGS_FILE + '.backup'
                try:
                    import shutil
                    shutil.copy2(SETTINGS_FILE, backup_file)
                    print(f"Settings file backed up to {backup_file}")
                except:
                    pass

            # Reset to safe defaults
            default_settings = {f'force_{key_name}_always_on': False
                              for key_name in self.keys.keys()}
            default_settings['start_at_bootup'] = False
            try:
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(default_settings, f, indent=2)
                print("Settings file reset to defaults")
            except:
                pass

    def load_settings(self):
        """Load settings from file, create defaults if file doesn't exist."""
        self.validate_settings()
        # Clean up any old registry entries before checking consistency
        self.cleanup_old_registry_entries()
        self.check_registry_consistency()

    def _save_settings_immediate(self):
        """Save current settings to file immediately."""
        settings = {f'force_{key_name}_always_on': key_data['force_on']
                   for key_name, key_data in self.keys.items()}
        settings['start_at_bootup'] = self.startup_enabled
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
        except IOError:
            pass

    def save_settings(self):
        """Save current settings to file with debouncing."""
        # Cancel any pending save
        if self._save_timer:
            self._save_timer.cancel()

        # Schedule save in 1 second to debounce rapid changes
        self._save_timer = threading.Timer(1.0, self._save_settings_immediate)
        self._save_timer.daemon = True
        self._save_timer.start()

    def toggle_startup(self):
        """Toggle startup at bootup."""
        self.startup_enabled = not self.startup_enabled
        if self.startup_enabled:
            self.enable_startup()
        else:
            self.disable_startup()
        self.save_settings()

    def enable_startup(self):
        """Add application to Windows startup via registry."""
        try:
            exe_path = os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])

            # Open the registry key for startup programs
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run",
                               0, winreg.KEY_SET_VALUE)

            # Set the value
            winreg.SetValueEx(key, "TrayLocker", 0, winreg.REG_SZ, f'"{exe_path}"')
            winreg.CloseKey(key)
        except (OSError, WindowsError):
            pass

    def disable_startup(self):
        """Remove application from Windows startup via registry."""
        try:
            # Open the registry key for startup programs
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Run",
                               0, winreg.KEY_SET_VALUE)

            # Delete the value if it exists
            try:
                winreg.DeleteValue(key, "TrayLocker")
            except FileNotFoundError:
                pass  # Value doesn't exist, which is fine

            winreg.CloseKey(key)
        except (OSError, WindowsError):
            pass

    def toggle_force_on(self, key_name):
        """Toggle force always on for a specific key."""
        if key_name in self.keys:
            self.keys[key_name]['force_on'] = not self.keys[key_name]['force_on']
            self.save_settings()

    def get_force_on(self, key_name):
        """Get force always on state for a specific key."""
        return self.keys.get(key_name, {}).get('force_on', False)

    def get_key_data(self, key_name):
        """Get all data for a specific key."""
        return self.keys.get(key_name, {})

class SettingsWindow:
    """
    GUI window for configuring TrayLocker settings.

    Provides a user interface for modifying application settings through
    a tkinter-based window with checkboxes and controls.

    Features:
    - Individual checkboxes for each lock key's "force always on" setting
    - Checkbox for enabling/disabling automatic startup at boot
    - Lightweight, non-blocking design that reuses window instances
    - Thread-safe operation with proper GUI thread management
    - Automatic persistence of settings changes

    The window is designed to be memory-efficient by maintaining a single
    instance that can be shown/hidden rather than creating new windows.
    """

    def __init__(self, key_manager):
        self.key_manager = key_manager
        # Store reference to the tkinter window (initially None)
        self.window = None
        # Dictionary to keep track of checkbox widgets for each setting
        self.checkboxes = {}
        # Thread for running tkinter mainloop
        self.gui_thread = None
        # Tkinter variable for startup checkbox
        self.startup_var = None

    def show(self):
        """
        Display the settings window, creating it if necessary.

        This method reuses the same window instance instead of creating
        a new one each time, which is more memory-efficient and provides
        a better user experience.
        """
        if self.window is not None and self.startup_var is not None:
            # Window already exists - just show it and update the checkbox states
            # This ensures the checkboxes reflect the current settings
            try:
                for key_name, var in self.checkboxes.items():
                    var.set(self.key_manager.get_force_on(key_name))
                self.startup_var.set(self.key_manager.startup_enabled)
                self.window.deiconify()  # Make window visible (undoes withdraw)
                self.window.lift()  # Bring to front
                self.window.focus_force()  # Give it focus
            except tk.TclError:
                # Window was destroyed, recreate it
                self.window = None
                self.startup_var = None
                self.checkboxes.clear()
                self._create_window()
            return

        # Create the window for the first time
        self._create_window()

    def _create_window(self):
        """Create the tkinter window and start its event loop in a separate thread."""
        def run_gui():
            """Run the tkinter mainloop in a separate thread."""
            try:
                self.window = tk.Tk()
                self.window.title("TrayLocker Settings")
                self.window.geometry("300x200")  # Fixed size window
                self.window.resizable(False, False)  # Don't allow resizing
                # Handle window close button (X) by calling our close method
                self.window.protocol("WM_DELETE_WINDOW", self.on_close)

                # Create a checkbox for each lock key's "force on" setting
                for key_name, key_data in self.key_manager.keys.items():
                    # Create a boolean variable to track this checkbox's state
                    var = tk.BooleanVar(value=key_data['force_on'])
                    self.checkboxes[key_name] = var
                    # Create the checkbox widget with descriptive text
                    cb = ttk.Checkbutton(self.window, text=f"Force {key_data['name']} Always On",
                                        variable=var, command=lambda k=key_name: self.toggle_force_on(k))
                    cb.pack(anchor=tk.W, padx=20, pady=5)  # Left-align with padding

                # Create checkbox for startup setting
                self.startup_var = tk.BooleanVar(value=self.key_manager.startup_enabled)
                startup_cb = ttk.Checkbutton(self.window, text="Start at Bootup",
                                            variable=self.startup_var, command=self.toggle_startup)
                startup_cb.pack(anchor=tk.W, padx=20, pady=10)

                # Version information label
                version_label = ttk.Label(self.window, text=f"TrayLocker {__version__}",
                                        font=("", 8), foreground="gray")
                version_label.pack(pady=(5, 0))

                # Close button to dismiss the window
                close_btn = ttk.Button(self.window, text="Close", command=self.on_close)
                close_btn.pack(pady=(0, 10))
                # Start the tkinter event loop
                self.window.mainloop()
            except Exception as e:
                print(f"GUI thread error: {e}")

        # Start the GUI in a separate daemon thread
        self.gui_thread = threading.Thread(target=run_gui, daemon=True, name="SettingsGUI")
        self.gui_thread.start()

    def toggle_force_on(self, key_name):
        """Toggle force always on for a key."""
        self.key_manager.toggle_force_on(key_name)

    def toggle_startup(self):
        """Toggle startup setting."""
        self.key_manager.toggle_startup()
        # Update the checkbox to reflect the actual state
        self.startup_var.set(self.key_manager.startup_enabled)

    def on_close(self):
        """Handle window close."""
        if self.window:
            self.window.withdraw()  # Hide the window instead of destroying it

    def cleanup(self):
        """Clean up GUI resources."""
        if self.window:
            try:
                # Use after() to schedule destruction on the GUI thread
                def destroy_window():
                    try:
                        if self.window:
                            self.window.quit()  # Stop the tkinter event loop
                            self.window.destroy()  # Destroy the window
                    except:
                        pass  # Ignore errors during cleanup
                    finally:
                        self.window = None

                # Schedule destruction on the GUI thread if it's still running
                if self.window.winfo_exists():
                    self.window.after(0, destroy_window)
                else:
                    self.window = None
            except:
                # If window access fails, just clear the reference
                self.window = None

        # Wait for GUI thread to finish (with timeout)
        if self.gui_thread and self.gui_thread.is_alive():
            self.gui_thread.join(timeout=2.0)

# Global manager instance
key_manager = LockKeyManager()

# Global settings window
settings_window = SettingsWindow(key_manager)

def is_lock_on(vk_code):
    """
    Check if a lock key is currently on.

    Args:
        vk_code: Virtual key code for the lock key (e.g., win32con.VK_NUMLOCK)

    Returns:
        bool: True if the lock key is on, False if off
    """
    return win32api.GetKeyState(vk_code) & 1

def toggle_lock(vk_code):
    """
    Toggle a lock key on or off by simulating a key press.

    Args:
        vk_code: Virtual key code for the lock key to toggle
    """
    win32api.keybd_event(vk_code, 0, 0, 0)
    win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)

def keep_all_locks():
    """
    Background thread that monitors and maintains lock key states.

    This function runs in a separate thread and continuously checks if any
    lock keys that should be "forced on" have been turned off by the user.
    If so, it automatically turns them back on.

    The thread checks every 2 seconds to balance responsiveness with CPU usage.
    It stops cleanly when the shutdown_event is set during application exit.
    """
    while not shutdown_event.is_set():
        # Check each lock key that should be forced on
        for key_name, key_data in key_manager.keys.items():
            # If this key should be forced on AND it's currently off, turn it on
            if key_manager.get_force_on(key_name) and not is_lock_on(key_data['vk']):
                toggle_lock(key_data['vk'])

        # Wait 2 seconds before checking again, but wake up immediately if shutting down
        shutdown_event.wait(2.0)
    print("Lock monitoring thread stopped")

def show_settings(icon, item):
    """
    Show the TrayLocker settings window.

    This is a callback function for the system tray menu.
    Called when user clicks "Settings" in any tray icon menu.

    Args:
        icon: The pystray icon that triggered this callback
        item: The menu item that was clicked
    """
    settings_window.show()

def exit_app(icon, item):
    """
    Cleanly shut down the entire TrayLocker application.

    This function performs an orderly shutdown sequence to ensure:
    1. No data loss (settings are saved)
    2. No resource leaks (threads stopped, GUI cleaned up)
    3. Clean system tray removal (icons stopped)
    4. Guaranteed exit (force quit if needed)

    The shutdown process is designed to be robust and handle various
    edge cases that could occur during application termination.
    """
    print("TrayLocker shutting down...")

    # Signal all background threads to stop their work loops
    shutdown_event.set()

    # Save settings immediately (don't wait for debounced save timer)
    key_manager._save_settings_immediate()

    # Cancel any pending settings save timer to prevent it from firing after shutdown
    if hasattr(key_manager, '_save_timer') and key_manager._save_timer:
        key_manager._save_timer.cancel()

    # Clear the icon cache to free up memory
    load_icon.cache_clear()

    # Clean up GUI resources (destroy tkinter windows)
    settings_window.cleanup()

    # Stop all system tray icons (removes them from taskbar)
    for icon_obj in icons.values():
        if icon_obj:
            icon_obj.stop()

    # Wait for all background threads to finish their work
    # Use timeouts to prevent hanging if threads are unresponsive
    for thread in running_threads:
        if thread.is_alive():
            thread.join(timeout=2.0)  # Wait up to 2 seconds per thread

    # If threads are still running after timeout, force immediate exit
    # This ensures the application always terminates, even in error conditions
    print("TrayLocker shutdown complete")
    os._exit(0)
def create_menu_update_handler(key_name):
    """
    Create a menu update handler function for a specific lock key.

    Each tray icon needs its own menu handler to manage the context menu
    that appears when right-clicking the tray icon.

    Args:
        key_name: Name of the lock key (e.g., 'numlock', 'capslock')

    Returns:
        function: Menu update handler that can be called to refresh the icon's menu
    """
    def update_menu(icon):
        """
        Update the system tray menu for this icon.

        Creates a menu with Settings and Exit options that are shared
        across all tray icons.
        """
        menu = pystray.Menu(
            pystray.MenuItem("Settings", show_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", exit_app)
        )
        icon.menu = menu
    return update_menu

# Create menu update handlers
update_numlock_menu = create_menu_update_handler('numlock')
update_capslock_menu = create_menu_update_handler('capslock')
update_scrollock_menu = create_menu_update_handler('scrollock')

def update_icon_state(icon, vk_code, icon_base_name):
    """
    Update a tray icon to reflect the current state of its lock key.

    Changes the icon image to show whether the corresponding lock key
    is currently on or off.

    Args:
        icon: The pystray icon object to update
        vk_code: Virtual key code for the lock key
        icon_base_name: Base name for icon files (e.g., 'icon_numlock')
    """
    state = "on" if is_lock_on(vk_code) else "off"
    icon_name = f"{icon_base_name}_{state}"
    try:
        new_image = load_icon(icon_name)
        icon.icon = new_image
    except FileNotFoundError:
        # Fallback to default icon if state-specific icon not found
        pass

# Global application state variables
# These need to be global as they're accessed by multiple threads and functions
# throughout the application lifecycle. All are initialized in main().

# Dictionary mapping lock key names to their system tray icon objects
# Key: lock key name (e.g., 'numlock'), Value: pystray.Icon instance
icons = {}

# Threading event for coordinated shutdown of all background threads
# When set, all monitoring and UI threads will exit their work loops cleanly
shutdown_event = threading.Event()

# List of all active background threads for proper shutdown coordination
# Includes lock monitor, icon updater, and individual tray icon threads
running_threads = []

@lru_cache(maxsize=16)
def load_icon(icon_name):
    """
    Load an icon image file with automatic caching.

    This function uses Python's LRU (Least Recently Used) cache to store
    up to 16 icon images in memory. This prevents reloading the same icon
    multiple times, which improves performance.

    The function handles both development (icons in current directory)
    and packaged executable (icons bundled with PyInstaller) scenarios.

    Args:
        icon_name: Name of the icon file (without .png extension)

    Returns:
        PIL Image object, or a transparent placeholder if file not found
    """
    # Handle different execution environments:
    # - When run as PyInstaller executable, icons are in _MEIPASS directory
    # - When run as script, icons are in current working directory
    if hasattr(sys, '_MEIPASS'):
        # Running as PyInstaller bundle
        icon_path = os.path.join(sys._MEIPASS, f'{icon_name}.png')
    else:
        # Running as regular Python script
        icon_path = f'{icon_name}.png'

    try:
        # Load and return the image
        return Image.open(icon_path)
    except FileNotFoundError:
        # If icon file doesn't exist, return a transparent placeholder
        # This prevents crashes and provides graceful degradation
        return Image.new('RGBA', (16, 16), (0, 0, 0, 0))

def create_icon(key_name):
    """
    Create and configure a system tray icon for a specific lock key.

    Sets up the icon with appropriate initial image, menu, and stores
    the reference for later management.

    Args:
        key_name: Name of the lock key (e.g., 'numlock', 'capslock', 'scrollock')

    Returns:
        pystray.Icon: The configured tray icon object
    """
    key_data = key_manager.get_key_data(key_name)
    icon_base = key_data.get('icon_base', f'icon_{key_name}')
    display_name = key_data.get('name', key_name.capitalize())

    image = load_icon(f'{icon_base}_off')  # Start with off state
    icon = pystray.Icon(f"{display_name} Tray", image, f"{display_name} Holder")

    # Store icon reference and set menu
    icons[key_name] = icon
    menu_updater = globals()[f'update_{key_name}_menu']
    menu_updater(icon)

    return icon



# Cache of previous icon states to prevent unnecessary icon updates
# Key: lock key name, Value: boolean (True = was on, False = was off)
# Used by update_all_icons() to avoid visual flicker from redundant updates
previous_states = {}

def update_all_icons():
    """
    Background thread that keeps tray icons synchronized with lock key states.

    This thread runs continuously and updates the tray icons to show the current
    state of each lock key (on/off). It only updates icons when their state
    actually changes to avoid unnecessary work and visual flicker.

    The thread checks every 1 second for responsive UI updates and stops
    cleanly when the application shuts down.
    """
    while not shutdown_event.is_set():
        # Check each lock key's current state
        for key_name, key_data in key_manager.keys.items():
            icon = icons.get(key_name)
            if icon:
                # Get current state from the keyboard hardware
                current_state = is_lock_on(key_data['vk'])
                # Get the state we showed last time
                previous_state = previous_states.get(key_name)

                # Only update the icon if the state has actually changed
                # This prevents unnecessary icon updates and visual flicker
                if current_state != previous_state:
                    update_icon_state(icon, key_data['vk'], key_data['icon_base'])
                    previous_states[key_name] = current_state

        # Check again in 1 second, but wake up immediately if shutting down
        shutdown_event.wait(1.0)
    print("Icon update thread stopped")

def signal_handler(signum, frame):
    """
    Handle system signals (SIGINT, SIGTERM) for clean application shutdown.

    Called when the system sends termination signals, such as when the user
    presses Ctrl+C or the system is shutting down.

    Args:
        signum: Signal number that was received
        frame: Current stack frame (unused)
    """
    print(f"Received signal {signum}, shutting down...")
    shutdown_event.set()

def main():
    """
    Main application entry point - sets up and runs TrayLocker.

    This function performs the complete application startup sequence:
    1. Ensures only one instance runs (mutex check)
    2. Sets up signal handlers for clean shutdown
    3. Loads settings and validates them
    4. Creates system tray icons
    5. Starts background threads for monitoring and UI updates
    6. Keeps the main thread alive until shutdown

    The application uses multiple threads to handle different responsibilities
    concurrently without blocking the UI.
    """
    global running_threads

    # Prevent multiple instances from running simultaneously
    # This uses a Windows "mutex" (mutual exclusion) object as a lock
    mutex_name = "TrayLocker_SingleInstance_Mutex"
    mutex = win32event.CreateMutex(None, False, mutex_name)
    if win32api.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("TrayLocker is already running. Exiting...")
        return

    # Set up handlers for system signals (Ctrl+C, system shutdown)
    # These ensure clean shutdown when the user or system wants to exit
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Preload all icon images into memory to avoid delays when switching states
    # This loads both "on" and "off" versions of each lock key icon
    for key_name, key_data in key_manager.keys.items():
        load_icon(f"{key_data['icon_base']}_on")
        load_icon(f"{key_data['icon_base']}_off")

    # Create system tray icons for each lock key
    # Each icon will show in the Windows system tray area
    for key_name in key_manager.keys:
        create_icon(key_name)

    # Start background thread to monitor and maintain lock key states
    # This thread automatically turns keys back on if they should be forced on
    lock_monitor_thread = threading.Thread(target=keep_all_locks, daemon=True, name="LockMonitor")
    lock_monitor_thread.start()
    running_threads.append(lock_monitor_thread)

    # Start background thread to keep tray icons updated with current key states
    # This ensures the icons always show the correct on/off appearance
    icon_thread = threading.Thread(target=update_all_icons, daemon=True, name="IconUpdater")
    icon_thread.start()
    running_threads.append(icon_thread)

    # Start a thread for each tray icon to handle its system tray presence
    # Each icon needs its own thread to process clicks and menu interactions
    for key_name, icon in icons.items():
        thread = threading.Thread(target=icon.run, daemon=True, name=f"TrayIcon-{key_name}")
        thread.start()
        running_threads.append(thread)

    # Main thread event loop - keeps the application running
    # We use an event to wait efficiently and respond to shutdown signals
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(1)  # Check shutdown event every second
    except KeyboardInterrupt:
        # User pressed Ctrl+C
        shutdown_event.set()

    # Perform clean shutdown of all components
    exit_app(None, None)

# Standard Python idiom: only run main() if this file is executed directly
# (not imported as a module by another script)
if __name__ == "__main__":
    main()