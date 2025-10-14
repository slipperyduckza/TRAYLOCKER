#![windows_subsystem = "windows"] // This tells Windows not to show a console window for our app

// Import necessary libraries for threading, timing, synchronization, tray icons, etc.
use std::thread; // For creating background threads
use std::time::Duration; // For time delays
use std::sync::{Arc, Mutex, mpsc}; // Arc for shared ownership, Mutex for safe sharing, mpsc for message passing
use std::sync::atomic::{AtomicBool, Ordering}; // For thread-safe boolean flags
use tray_icon::{TrayIconBuilder, menu::{Menu, MenuItem, MenuEvent, MenuId}}; // For system tray icons and menus
use single_instance::SingleInstance; // To ensure only one instance of the app runs
use std::collections::HashMap; // For storing tray icons by key
use windows::Win32::System::Registry::*; // For Windows registry access (for startup)
use std::os::windows::ffi::OsStrExt; // For converting strings to Windows format
use bytemuck; // For casting data types safely
use eframe::egui; // For the GUI framework
use crate::settings::SettingsManager; // Our custom settings manager

/// Messages that threads can send to the main thread to control the app.
/// For example, to show the settings window or to quit the app.
#[derive(Debug)]
enum Command {
    ShowSettings, // Tell the main thread to open the settings window
    Shutdown,     // Tell the main thread to close the app
}
use windows::Win32::UI::WindowsAndMessaging::*;

/// This module handles all the user settings for the app.
/// It includes what keys to lock, whether to start at boot, etc.
pub mod settings {
use std::path::PathBuf;
use std::fs;
use serde::{Deserialize, Serialize};
use serde_json;
use dirs::data_local_dir;
use windows::Win32::UI::Input::KeyboardAndMouse::{VK_NUMLOCK, VK_CAPITAL, VK_SCROLL};

/// The types of keyboard lock keys we can control.
/// These are the Num Lock, Caps Lock, and Scroll Lock keys.
#[allow(dead_code)] // Some variants might not be used, but we keep them for completeness
#[derive(Debug, Clone, Copy, Eq, Hash, PartialEq)] // Traits for debugging, copying, comparing, and hashing
pub enum LockKey {
    NumLock,   // The Num Lock key
    CapsLock,  // The Caps Lock key
    ScrollLock, // The Scroll Lock key
}

impl LockKey {
    /// Get a string name for the key, used for file paths or display.
    pub fn name(&self) -> &str {
        match self {
            LockKey::NumLock => "numlock",
            LockKey::CapsLock => "capslock",
            LockKey::ScrollLock => "scrollock",
        }
    }

    /// Get the virtual key code for this key, used by Windows to identify keys.
    pub fn vk_code(&self) -> u32 {
        match self {
            LockKey::NumLock => VK_NUMLOCK.0 as u32,
            LockKey::CapsLock => VK_CAPITAL.0 as u32,
            LockKey::ScrollLock => VK_SCROLL.0 as u32,
        }
    }
}

/// This struct stores all the settings the user can change.
/// Each field is a boolean (true/false) for whether to force a key on or off.
#[derive(Serialize, Deserialize, Clone, Default)] // Traits for saving/loading from JSON, copying, and default values
pub struct Settings {
    #[serde(default)] // Use default (false) if not in file
    pub force_numlock_on: bool,        // Force Num Lock to always be on
    #[serde(default)]
    pub force_capslock_on: bool,       // Force Caps Lock to always be on
    #[serde(default)]
    pub force_scrollock_on: bool,      // Force Scroll Lock to always be on
    #[serde(default)]
    pub force_numlock_always_off: bool, // Force Num Lock to always be off
    #[serde(default)]
    pub force_capslock_always_off: bool, // Force Caps Lock to always be off
    #[serde(default)]
    pub force_scrollock_always_off: bool, // Force Scroll Lock to always be off
    #[serde(default)]
    pub start_at_boot: bool,           // Whether to start the app when Windows boots
}

/// This struct handles saving and loading the settings to a file.
/// It keeps the current settings in memory and knows where to save them.
pub struct SettingsManager {
    pub settings: Settings, // The current settings
    path: PathBuf,          // The file path where settings are saved
}

impl SettingsManager {
    /// Create a new settings manager. It loads settings from file if it exists,
    /// or creates default settings if not.
    pub fn new() -> std::result::Result<Self, Box<dyn std::error::Error>> {
        // Find the user's local app data folder, create TrayLocker folder
        let path = data_local_dir().unwrap().join("TrayLocker").join("settings.json");
        fs::create_dir_all(path.parent().unwrap())?; // Make sure the folder exists
        // Load settings from file, or use defaults
        let settings = if path.exists() {
            let content = fs::read_to_string(&path)?; // Read the file
            serde_json::from_str(&content)? // Parse the JSON
        } else {
            Settings::default() // Start with all false
        };
        Ok(SettingsManager { settings, path })
    }

    /// Get a list of all the lock keys we support.
    pub fn get_keys(&self) -> &[LockKey] {
        &[LockKey::NumLock, LockKey::CapsLock, LockKey::ScrollLock]
    }

    /// Check if we should force this key to be on.
    pub fn get_force_on(&self, key: LockKey) -> bool {
        match key {
            LockKey::NumLock => self.settings.force_numlock_on,
            LockKey::CapsLock => self.settings.force_capslock_on,
            LockKey::ScrollLock => self.settings.force_scrollock_on,
        }
    }

    /// Check if we should force this key to be off.
    pub fn get_force_off(&self, key: LockKey) -> bool {
        match key {
            LockKey::NumLock => self.settings.force_numlock_always_off,
            LockKey::CapsLock => self.settings.force_capslock_always_off,
            LockKey::ScrollLock => self.settings.force_scrollock_always_off,
        }
    }

    /// Save the current settings to the JSON file.
    pub fn save(&self) -> std::result::Result<(), Box<dyn std::error::Error>> {
        let content = serde_json::to_string_pretty(&self.settings)?; // Convert to nice JSON
        fs::write(&self.path, content)?; // Write to file
        Ok(())
    }
}
}

/// This module has functions to check if a key is locked and to toggle it.
/// It uses Windows API calls to interact with the keyboard.
pub mod keyboard {
    use windows::Win32::UI::Input::KeyboardAndMouse::{GetKeyState, keybd_event, KEYBD_EVENT_FLAGS, KEYEVENTF_KEYUP};

    /// Check if a lock key is currently on (locked).
    /// Returns true if the key is locked, false if not.
    pub fn is_lock_on(vk_code: u32) -> bool {
        unsafe {
            (GetKeyState(vk_code as i32) & 1) != 0 // Windows API: check the least significant bit
        }
    }

    /// Toggle (press and release) a lock key to change its state.
    pub fn toggle_lock(vk_code: u32) {
        unsafe {
            keybd_event(vk_code as u8, 0, KEYBD_EVENT_FLAGS(0), 0); // Press the key
            keybd_event(vk_code as u8, 0, KEYEVENTF_KEYUP, 0);      // Release the key
        }
    }
}

/// This module loads the icon images for the system tray.
/// It has different icons for on/off states of each key.
pub mod tray {
    use tray_icon::Icon;
    use image;
    use crate::settings::LockKey;

    // These are the icon images embedded in the binary at compile time.
    // Each is a PNG file included as bytes.
    static ICON_NUMLOCK_ON: &[u8] = include_bytes!("../icon_numlock_on.png");
    static ICON_NUMLOCK_OFF: &[u8] = include_bytes!("../icon_numlock_off.png");
    static ICON_CAPSLOCK_ON: &[u8] = include_bytes!("../icon_capslock_on.png");
    static ICON_CAPSLOCK_OFF: &[u8] = include_bytes!("../icon_capslock_off.png");
    static ICON_SCROLLLOCK_ON: &[u8] = include_bytes!("../icon_scrollock_on.png");
    static ICON_SCROLLLOCK_OFF: &[u8] = include_bytes!("../icon_scrollock_off.png");

    /// Load the correct icon for a key and its state (on or off).
    pub fn load_icon(key: LockKey, state: bool) -> Result<Icon, Box<dyn std::error::Error>> {
        // Pick the right icon bytes based on key and state
        let bytes = match (key, state) {
            (LockKey::NumLock, true) => ICON_NUMLOCK_ON,
            (LockKey::NumLock, false) => ICON_NUMLOCK_OFF,
            (LockKey::CapsLock, true) => ICON_CAPSLOCK_ON,
            (LockKey::CapsLock, false) => ICON_CAPSLOCK_OFF,
            (LockKey::ScrollLock, true) => ICON_SCROLLLOCK_ON,
            (LockKey::ScrollLock, false) => ICON_SCROLLLOCK_OFF,
        };
        // Load the PNG image from memory
        let image = image::load_from_memory_with_format(bytes, image::ImageFormat::Png)?;
        let rgba = image.to_rgba8(); // Convert to RGBA format
        let (width, height) = rgba.dimensions(); // Get size
        let rgba_bytes = rgba.into_raw(); // Get raw bytes
        Ok(Icon::from_rgba(rgba_bytes, width, height)?) // Create the icon
    }
}




/// This struct manages the settings window.
/// It holds a reference to the settings manager so it can save changes.
pub struct SettingsWindow {
    settings_manager: Arc<Mutex<SettingsManager>>, // Shared settings manager
}

impl SettingsWindow {
    /// Create a new settings window with the given settings manager.
    pub fn new(settings_manager: Arc<Mutex<SettingsManager>>) -> Self {
        SettingsWindow { settings_manager }
    }

    /// Show the settings window. This runs the GUI event loop until the window closes.
    pub fn show(&self) -> Result<(), Box<dyn std::error::Error>> {
        // Set up the window options: size 400x400, active
        let options = eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default()
                .with_inner_size([400.0, 400.0])
                .with_active(true),
            ..Default::default()
        };
        // Run the GUI app with our SettingsApp
        eframe::run_native(
            "TrayLocker Settings", // Window title
            options,
            Box::new(|cc| Ok(Box::new(SettingsApp::new(self.settings_manager.clone(), cc)))), // Create the app
        )?;
        Ok(())
    }
}

/// The GUI app for the settings window.
/// It displays checkboxes and buttons for changing settings.
pub struct SettingsApp {
    settings_manager: Arc<Mutex<SettingsManager>>, // To save changes
    settings: crate::settings::Settings,           // Local copy of settings to edit
}

impl SettingsApp {
    /// Create the settings app. Load the current settings from the manager.
    fn new(settings_manager: Arc<Mutex<SettingsManager>>, _cc: &eframe::CreationContext<'_>) -> Self {
        // Copy the current settings to edit locally
        let settings = {
            let sm = settings_manager.lock().unwrap(); // Lock to read
            sm.settings.clone() // Clone the settings
        };
        SettingsApp { settings_manager, settings }
    }
}

impl eframe::App for SettingsApp {
    /// This function is called every frame to draw the GUI.
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("TrayLocker Settings"); // Title

            // Checkboxes for each setting
            ui.checkbox(&mut self.settings.force_numlock_on, "Force NumLock On");
            ui.checkbox(&mut self.settings.force_numlock_always_off, "Force NumLock Always Off");
            ui.checkbox(&mut self.settings.force_capslock_on, "Force CapsLock On");
            ui.checkbox(&mut self.settings.force_capslock_always_off, "Force CapsLock Always Off");
            ui.checkbox(&mut self.settings.force_scrollock_on, "Force ScrollLock On");
            ui.checkbox(&mut self.settings.force_scrollock_always_off, "Force ScrollLock Always Off");
            ui.checkbox(&mut self.settings.start_at_boot, "Start at Boot");

            ui.separator(); // A line to separate

            // Grid for the buttons
            egui::Grid::new("settings_grid")
                .num_columns(2) // Two columns
                .spacing([10.0, 10.0]) // Space between items
                .show(ui, |ui| {
                    // Save button: saves the settings
                    let save_button = egui::Button::new(egui::RichText::new("Save").color(egui::Color32::WHITE).strong())
                        .fill(egui::Color32::from_rgb(100, 149, 237)) // Blue color
                        .stroke(egui::Stroke::new(2.0, egui::Color32::BLACK)) // Black border
                        .min_size(egui::Vec2::new(80.0, 35.0)); // Minimum size
                    if ui.add(save_button).on_hover_text("Save settings").clicked() {
                        // Lock the manager, update settings, save to file
                        if let Ok(mut manager) = self.settings_manager.lock() {
                            manager.settings = self.settings.clone();
                            if let Err(e) = manager.save() {
                                eprintln!("Failed to save settings: {}", e); // Print error if save fails
                            }
                        }
                    }
                    ui.end_row(); // Next row

                    // Visibility button: opens Windows settings
                    let visibility_button = egui::Button::new(egui::RichText::new("Visibility").color(egui::Color32::WHITE).strong())
                        .fill(egui::Color32::from_rgb(222, 184, 135)) // Brown color
                        .stroke(egui::Stroke::new(2.0, egui::Color32::BLACK)) // Black border
                        .min_size(egui::Vec2::new(100.0, 35.0)); // Minimum size
                    if ui.add(visibility_button).on_hover_text("Open Taskbar Settings").clicked() {
                        // Run the command to open Windows Taskbar settings
                        std::process::Command::new("explorer")
                            .arg("ms-settings:taskbar")
                            .spawn()
                            .unwrap();
                    }
                    ui.end_row();
                });

            // Help text below the buttons
            ui.label("To always show your TrayLocker icons, click and expand the [Other system tray icons] drop-down and toggle traylocker.exe button to [ON]");
        });
    }
}

/// This is the main function where the app starts.
/// It sets up everything: settings, tray icons, background threads, and the main loop.
fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    // Set up logging so we can see debug messages
    env_logger::init();

    // Make sure only one copy of the app is running
    let instance = SingleInstance::new("TrayLocker_SingleInstance")?;
    if !instance.is_single() {
        println!("TrayLocker is already running. Exiting...");
        return Ok(());
    }

    // Load or create the settings
    let settings_manager = Arc::new(Mutex::new(crate::settings::SettingsManager::new()?));

    // If the user wants to start at boot, add to Windows registry
    {
        let settings = settings_manager.lock().unwrap(); // Read current settings
        if settings.settings.start_at_boot {
            // Get the path to this exe file
            let exe_path = std::env::current_exe().unwrap();
            // Convert to Windows wide string format
            let value: Vec<u16> = exe_path.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
            // Path to the registry key for startup programs
            let key_path: Vec<u16> = "Software\\Microsoft\\Windows\\CurrentVersion\\Run".encode_utf16().chain(std::iter::once(0)).collect();
            let name: Vec<u16> = "TrayLocker".encode_utf16().chain(std::iter::once(0)).collect();
            unsafe {
                // Open or create the registry key
                let mut hkey: HKEY = HKEY::default();
                let result = RegCreateKeyExW(HKEY_CURRENT_USER, windows::core::PCWSTR(key_path.as_ptr()), 0, None, REG_OPTION_NON_VOLATILE, KEY_WRITE, None, &mut hkey, None);
                if result.is_ok() {
                    // Set the value to our exe path
                    let _ = RegSetValueExW(hkey, windows::core::PCWSTR(name.as_ptr()), 0, REG_SZ, Some(bytemuck::cast_slice(&value)));
                    let _ = RegCloseKey(hkey); // Close the key
                }
            }
        }
    }

    // Create the settings window (but don't show it yet)
    let settings_window = Arc::new(Mutex::new(SettingsWindow::new(settings_manager.clone())));

    // Set up channels for threads to send messages to the main thread
    let (tx, rx) = mpsc::channel(); // For commands like show settings or shutdown

    // Shared flags and channels for controlling the app
    let shutdown_flag = Arc::new(AtomicBool::new(false)); // True when app should quit
    let (update_tx, update_rx) = mpsc::channel(); // For tray threads to tell main thread to update icons
    let mut tray_icons = HashMap::new(); // Store the tray icons by key

    // Now create the tray icons and background threads

    // Get the list of keys we need icons for
    let keys = {
        let settings = settings_manager.lock().unwrap();
        settings.get_keys().to_vec() // Clone the array to a vector
    };

    let mut update_handles = vec![]; // Store handles to the background threads

    println!("About to create tray icons");
    for &key in &keys {
        println!("Creating tray icon for {}", key.name());
        // Create a menu for this icon with Settings and Exit options
        let menu = Menu::new();
        let settings_item = MenuItem::with_id(MenuId("settings".to_string()), "Settings", true, None);
        let exit_item = MenuItem::with_id(MenuId("exit".to_string()), "Exit", true, None);
        menu.append(&settings_item)?;
        menu.append(&exit_item)?;

        // Load the icon (start with off state)
        let icon = crate::tray::load_icon(key, false)?;
        println!("Icon loaded for {}", key.name());

        // Build the tray icon with menu and icon
        let tray_icon = TrayIconBuilder::new()
            .with_menu(Box::new(menu))
            .with_icon(icon)
            .build()?;
        println!("Tray icon built for {}", key.name());

        log::info!("Tray icon created for {}", key.name());
        tray_icons.insert(key, tray_icon); // Store it in the map

        // Start a background thread to monitor and control this key
        let settings_clone = settings_manager.clone(); // Share settings
        let shutdown_clone = shutdown_flag.clone(); // Share shutdown flag
        let update_tx_clone = update_tx.clone(); // Share update channel
        let handle = thread::spawn(move || {
            let mut previous_state = None; // Remember the last state
            while !shutdown_clone.load(Ordering::Relaxed) { // Loop until shutdown
                // Check current settings
                let settings = settings_clone.lock().unwrap();
                let force_on = settings.get_force_on(key);
                let force_off = settings.get_force_off(key);
                drop(settings); // Unlock

                // Check if the key is currently on
                let current_state = crate::keyboard::is_lock_on(key.vk_code());

                // If we need to force it on and it's off, toggle it
                if force_on && !current_state {
                    crate::keyboard::toggle_lock(key.vk_code());
                } else if force_off && current_state { // If force off and it's on, toggle
                    crate::keyboard::toggle_lock(key.vk_code());
                }

                // If the state changed, tell the main thread to update the icon
                if Some(current_state) != previous_state {
                    update_tx_clone.send((key, current_state)).unwrap();
                    previous_state = Some(current_state);
                }

                thread::sleep(Duration::from_secs(1)); // Wait 1 second before checking again
            }
        });
        update_handles.push(handle); // Save the thread handle
    }

    // Tray event handling is done in the main loop

    // Main loop: keep the app running, handle messages and events
    let mut msg = MSG::default(); // Windows message struct
    while !shutdown_flag.load(Ordering::Relaxed) { // Loop until shutdown
        unsafe {
            // Check for Windows messages (like tray events)
            if PeekMessageW(&mut msg, None, 0, 0, PM_REMOVE).as_bool() {
                TranslateMessage(&msg); // Translate key messages
                DispatchMessageW(&msg); // Send to window procedure
            } else {
                thread::sleep(Duration::from_millis(10)); // Short sleep if no messages
            }
        }
        // Check if any thread wants to update an icon
        if let Ok((key, state)) = update_rx.try_recv() {
            if let Some(tray_icon) = tray_icons.get(&key) {
                let icon = crate::tray::load_icon(key, state).unwrap();
                let _ = tray_icon.set_icon(Some(icon)); // Change the icon
            }
        }
        // Check for commands from threads
        if let Ok(cmd) = rx.try_recv() {
            match cmd {
                Command::ShowSettings => {
                    let _ = settings_window.lock().unwrap().show(); // Open settings window
                }
                Command::Shutdown => {
                    shutdown_flag.store(true, Ordering::Relaxed); // Set shutdown flag
                }
            }
        }
        // Check for tray menu clicks
        if let Ok(event) = MenuEvent::receiver().try_recv() {
            match event.id.0.as_str() {
                "settings" => tx.send(Command::ShowSettings).unwrap(), // Send show command
                "exit" => tx.send(Command::Shutdown).unwrap(), // Send shutdown command
                _ => {} // Ignore other events
            }
        }
    }

    // Cleanup: wait for all threads to finish
    println!("TrayLocker shutting down...");
    for handle in update_handles {
        handle.join().unwrap(); // Wait for each thread to end
    }

    Ok(())
}

