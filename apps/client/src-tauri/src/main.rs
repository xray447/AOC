// AOC Tauri 外壳：拉起 aoc-core 与 aoc-simlink，随机端口 + token，再让窗口指向本地 SPA。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::Manager;

struct Children(Mutex<Vec<Child>>);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn home_dir() -> PathBuf {
    if let Ok(home) = std::env::var("AOC_HOME") {
        return PathBuf::from(home);
    }
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| {
        std::env::var("USERPROFILE").unwrap_or_else(|_| ".".into())
    });
    PathBuf::from(base).join("AOC")
}

fn dev_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("..")
}

fn find_exe(name: &str) -> Option<PathBuf> {
    if let Ok(explicit) = std::env::var(format!("AOC_{}_EXE", name.to_uppercase().replace('-', "_"))) {
        let p = PathBuf::from(explicit);
        if p.exists() {
            return Some(p);
        }
    }
    None
}

fn spawn_core(port: u16, token: &str, home: &PathBuf, static_dir: &PathBuf,
              resource_dir: Option<&PathBuf>) -> Option<Child> {
    if let Some(exe) = find_exe("aoc-core") {
        return Command::new(exe)
            .args(["--port", &port.to_string(), "--token", token, "--home", &home.to_string_lossy(),
                   "--static-dir", &static_dir.to_string_lossy()])
            .spawn()
            .ok();
    }
    let bundled = resource_dir.map(|dir| dir.join("aoc-core").join("main.py"))
        .filter(|path| path.exists());
    let script = bundled.unwrap_or_else(|| dev_root().join("apps").join("aoc-core").join("main.py"));
    if !script.exists() {
        eprintln!("aoc-core/main.py not found: {}", script.display());
        return None;
    }
    Command::new("python")
        .arg("-X")
        .arg("utf8")
        .arg(script)
        .args(["--port", &port.to_string(), "--token", token, "--home", &home.to_string_lossy(),
               "--static-dir", &static_dir.to_string_lossy()])
        .spawn()
        .ok()
}

fn spawn_simlink(token: &str, home: &PathBuf, resource_dir: Option<&PathBuf>) -> Option<Child> {
    let mut candidates = Vec::new();
    if let Some(dir) = resource_dir {
        candidates.push(dir.join("simlink").join("aoc-simlink.exe"));
    }
    candidates.extend([
        dev_root().join("apps").join("simlink").join("bin").join("Release").join("net8.0").join("win-x64").join("aoc-simlink.exe"),
        dev_root().join("apps").join("simlink").join("bin").join("Debug").join("net8.0").join("aoc-simlink.exe"),
        dev_root().join("apps").join("simlink").join("bin").join("Release").join("net8.0").join("aoc-simlink.exe"),
    ]);
    if let Some(exe) = find_exe("simlink") {
        candidates.insert(0, exe);
    }
    let exe = candidates.into_iter().find(|p| p.exists())?;
    Command::new(exe)
        .args(["--port", "0", "--token", token, "--home", &home.to_string_lossy()])
        .spawn()
        .ok()
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let home = home_dir();
            std::fs::create_dir_all(&home).ok();
            let token = uuid::Uuid::new_v4().simple().to_string();
            let simlink_token = uuid::Uuid::new_v4().simple().to_string();
            let port = free_port();

            let resource_dir = app.path().resource_dir().ok();
            let static_dir = resource_dir
                .as_ref()
                .map(|p| p.join("client"))
                .filter(|p| p.exists())
                .unwrap_or_else(|| dev_root().join("apps").join("client").join("dist"));

            let mut children = Vec::new();
            match spawn_core(port, &token, &home, &static_dir, resource_dir.as_ref()) {
                Some(child) => children.push(child),
                None => eprintln!("failed to spawn aoc-core"),
            }
            if let Some(child) = spawn_simlink(&simlink_token, &home, resource_dir.as_ref()) {
                children.push(child);
            } else {
                eprintln!("aoc-simlink not found; telemetry disabled until built");
            }
            app.manage(Children(Mutex::new(children)));

            let window = app.get_webview_window("main").unwrap();
            let url = format!("http://127.0.0.1:{port}/");
            let win = window.clone();
            thread::spawn(move || {
                for _ in 0..150 {
                    if TcpStream::connect(("127.0.0.1", port)).is_ok() {
                        break;
                    }
                    thread::sleep(Duration::from_millis(100));
                }
                if let Ok(parsed) = tauri::Url::parse(&url) {
                    let _ = win.navigate(parsed);
                }
                let _ = win.show();
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(children) = window.app_handle().try_state::<Children>() {
                    if let Ok(mut list) = children.0.lock() {
                        for child in list.iter_mut() {
                            let _ = child.kill();
                        }
                        list.clear();
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error running AOC client");
}
