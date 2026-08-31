// Keeps a second console window from appearing on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // WebKitGTK's DMABUF renderer takes the window down on a number of Wayland
    // systems at startup — on this development machine (CachyOS, webkit2gtk-4.1)
    // reliably with "Error 71 (protocol error) dispatching to Wayland display",
    // before anything was drawn. Without that renderer it starts cleanly.
    //
    // Only set when nothing is prescribed: whoever wants the acceleration and
    // has a system where it works sets the variable to `0` themselves.
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        // SAFETY: runs before any other thread starts, so nothing else can be
        // reading the environment at the same time.
        unsafe { std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1") };
    }

    edge_dashboard_gui_lib::run()
}
