// Skeleton, not compiled: see ../../README.md.
//
// Starts `charpente studio` for a folder, opens a window on the address it prints, and stops it when the window closes.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct Server(Mutex<Option<Child>>);

/// The folder to open: the first command-line argument, else the current directory.
fn project_folder() -> String {
    std::env::args().nth(1).unwrap_or_else(|| ".".to_string())
}

/// Start `charpente studio --json` and return the child and the address it printed.
fn start_studio(folder: &str) -> Result<(Child, String), String> {
    let mut child = Command::new("charpente")
        .args(["studio", "--no-browser", "--json", "--root", folder])
        .stdin(Stdio::piped()) // kept open: closing it is one way to ask the server to stop
        .stdout(Stdio::piped())
        .spawn()
        .map_err(|e| format!("cannot start charpente (is it on PATH?): {e}"))?;
    let stdout = child.stdout.take().ok_or("no output from charpente")?;
    let mut line = String::new();
    BufReader::new(stdout).read_line(&mut line).map_err(|e| e.to_string())?;
    let info: serde_json::Value = serde_json::from_str(&line).map_err(|e| format!("unexpected output {line:?}: {e}"))?;
    let url = info["charpente-studio"]["url"].as_str().ok_or("no address in the output")?.to_string();
    Ok((child, url))
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let (child, url) = start_studio(&project_folder())?;
            app.manage(Server(Mutex::new(Some(child))));
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse()?))
                .title("Charpente Studio")
                .inner_size(1400.0, 900.0)
                .build()?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(server) = window.app_handle().try_state::<Server>() {
                    if let Some(mut child) = server.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Charpente Studio");
}
