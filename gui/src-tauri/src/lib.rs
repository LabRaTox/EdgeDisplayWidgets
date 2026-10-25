//! Window frame for the settings interface.
//!
//! Deliberately thin: all the logic lives in the Python backend, which runs as
//! its own process and is reached over HTTP on 127.0.0.1 (see
//! `backend/main.py`). The same interface therefore runs unchanged in a
//! browser tab against the same backend — useful while developing, and the
//! reason the kiosk needs no part of this.

use std::collections::HashSet;
use std::io::Read;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{DragDropEvent, Manager};

/// Largest file that can be dropped into the window. Plugin archives are
/// small; the limit only keeps a video dragged in by mistake from ending up
/// in memory whole. The same 64 MB the store accepts.
const MAX_DROPPED: u64 = 64 * 1024 * 1024;

/// Paths that were really dropped into the window just now.
///
/// Only these may be read by the page. Without the list, any script in the
/// window could ask for any file of the user.
#[derive(Default)]
struct Dropped(Mutex<HashSet<PathBuf>>);

fn remember_dropped(app: &tauri::AppHandle, event: &DragDropEvent) {
    if let DragDropEvent::Drop { paths, .. } = event {
        if let Some(state) = app.try_state::<Dropped>() {
            if let Ok(mut list) = state.0.lock() {
                list.clear();
                list.extend(paths.iter().cloned());
            }
        }
    }
}

/// Read a file that was dragged from the file manager into the window.
///
/// WebKitGTK does not hand a dropped file to the page, only its path as
/// `text/uri-list` (measured with Dolphin under Plasma 6, the same as in
/// DECK//SWITCH). The page cannot open a `file://` path itself, so the window
/// reads the file and returns its bytes. Only paths from the last drop, only
/// regular files up to `MAX_DROPPED`.
///
/// Errors come back as a code (`not-dropped`, `not-a-file`, `too-large`,
/// `io:…`); the page puts them into words in its own language.
#[tauri::command]
fn read_dropped_file(
    path: String,
    dropped: tauri::State<'_, Dropped>,
) -> Result<tauri::ipc::Response, String> {
    let path = PathBuf::from(&path);
    let allowed = dropped
        .0
        .lock()
        .map(|mut list| list.remove(&path))
        .unwrap_or(false);
    if !allowed {
        return Err("not-dropped".into());
    }
    // Checked before opening: a named pipe would make `open` hang.
    let info = std::fs::metadata(&path).map_err(|e| format!("io:{e}"))?;
    if !info.is_file() {
        return Err("not-a-file".into());
    }
    if info.len() > MAX_DROPPED {
        return Err("too-large".into());
    }
    let file = std::fs::File::open(&path).map_err(|e| format!("io:{e}"))?;
    // Read with a ceiling: the size from a moment ago may have changed, and
    // some files report none at all.
    let mut data = Vec::new();
    file.take(MAX_DROPPED + 1)
        .read_to_end(&mut data)
        .map_err(|e| format!("io:{e}"))?;
    if data.len() as u64 > MAX_DROPPED {
        return Err("too-large".into());
    }
    Ok(tauri::ipc::Response::new(data))
}

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
        .manage(Dropped::default())
        // Whether a drop is reported on the window or on the webview depends
        // on how the window is built. Both remember the paths.
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::DragDrop(drop) = event {
                remember_dropped(window.app_handle(), drop);
            }
        })
        .on_webview_event(|webview, event| {
            if let tauri::WebviewEvent::DragDrop(drop) = event {
                remember_dropped(webview.app_handle(), drop);
            }
        })
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
        .invoke_handler(tauri::generate_handler![start_dashboard, open_url, read_dropped_file])
        .run(tauri::generate_context!())
        .expect("could not start the settings window");
}
