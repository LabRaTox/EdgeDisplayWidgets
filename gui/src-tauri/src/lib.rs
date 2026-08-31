//! Window frame for the settings interface.
//!
//! Deliberately thin: all the logic lives in the Python backend, which runs as
//! its own process and is reached over HTTP on 127.0.0.1 (see
//! `backend/main.py`). The same interface therefore runs unchanged in a
//! browser tab against the same backend — useful while developing, and the
//! reason the kiosk needs no part of this.

use tauri::Manager;

/// Units the dashboard consists of, in the order they should come up.
const UNITS: [&str; 2] = ["edge-dashboard.service", "edge-kiosk.service"];

/// Start the dashboard, for when this window finds nothing to talk to.
///
/// The window is normally opened from the tray icon, which only exists while
/// the backend runs, so an unreachable backend means it was stopped on
/// purpose (the tray's own Quit does exactly that) or never started. Either
/// way the useful answer is to start it rather than to explain a systemctl
/// line, so this is what the offline banner calls.
///
/// Both units together: the kiosk was taken down with the backend, and a
/// backend with a dark display is not what anyone meant by "start it".
/// `systemctl start` on a running unit does nothing, so this is safe to call
/// whenever the window cannot reach anything.
#[tauri::command]
fn start_dashboard() -> Result<(), String> {
    let output = std::process::Command::new("systemctl")
        .arg("--user")
        .arg("start")
        .args(UNITS)
        .output()
        .map_err(|error| format!("systemctl could not be run: {error}"))?;

    if output.status.success() {
        return Ok(());
    }
    let message = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(if message.is_empty() {
        "systemctl failed without a message".to_string()
    } else {
        message
    })
}

/// Open a link in the user's browser.
///
/// A plain `<a href>` in this window would navigate the webview itself, which
/// would replace the settings UI with a web page and no way back. The URL is
/// checked here rather than trusted: the page is ours, but `xdg-open` acts on
/// whatever scheme it is handed, and `file://` or a desktop entry would be a
/// very different thing to open.
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    if !(url.starts_with("https://") || url.starts_with("http://")) {
        return Err("only http and https links can be opened".into());
    }
    std::process::Command::new("xdg-open")
        .arg(&url)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("could not open the link: {error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Single instance, because the tray icon is the normal way in: every
        // click on it runs this binary, and without this each click would
        // stack up another window. The second process hands its argv to the
        // first one and exits; the first one shows itself instead.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                // `show` before `unminimize`: a window closed to the tray is
                // hidden, not minimised, and unminimising a hidden window
                // does nothing visible.
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![start_dashboard, open_url])
        .run(tauri::generate_context!())
        .expect("could not start the settings window");
}
