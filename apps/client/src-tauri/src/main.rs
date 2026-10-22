// AOC Tauri 外壳：拉起 aoc-core 与 aoc-simlink，随机端口 + token，再让窗口指向本地 SPA。
// 生产构建不弹控制台窗口（CREATE_NO_WINDOW），子进程日志写 %LOCALAPPDATA%\AOC\logs；
// 关闭主窗口只最小化到托盘，托盘菜单可打开客户端 / 日志目录 / 退出（P-11 / A-32）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs::OpenOptions,
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, WindowEvent};

/// 单实例锁：已有一个 AOC 在跑时第二个进程直接退出，避免起两套 sidecar。
const INSTANCE_PORT: u16 = 47821;

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

/// 生产构建隐藏子进程控制台窗口；debug 构建保留，方便看 python/dotnet 输出。
#[cfg(all(windows, not(debug_assertions)))]
fn hide_console(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(any(not(windows), debug_assertions))]
fn hide_console(_cmd: &mut Command) {}

/// stdout/stderr 落到同一个日志文件（追加）；打不开就丢弃，绝不影响启动。
fn log_stdio(log_dir: &Path, name: &str) -> (Stdio, Stdio) {
    let path = log_dir.join(name);
    let open = || OpenOptions::new().create(true).append(true).open(&path);
    match (open(), open()) {
        (Ok(out), Ok(err)) => (Stdio::from(out), Stdio::from(err)),
        _ => (Stdio::null(), Stdio::null()),
    }
}

fn spawn_core(port: u16, token: &str, home: &PathBuf, static_dir: &PathBuf,
              resource_dir: Option<&PathBuf>, log_dir: &Path) -> Option<Child> {
    let (out, err) = log_stdio(log_dir, "core.log");
    if let Some(exe) = find_exe("aoc-core") {
        let mut cmd = Command::new(exe);
        cmd.args(["--port", &port.to_string(), "--token", token, "--home", &home.to_string_lossy(),
                  "--static-dir", &static_dir.to_string_lossy()]);
        hide_console(&mut cmd);
        return cmd.stdout(out).stderr(err).spawn().ok();
    }
    // 自包含产物：resources/aoc-core/aoc-core.exe（PyInstaller onedir）
    let bundled_exe = resource_dir
        .map(|dir| dir.join("aoc-core").join("aoc-core.exe"))
        .filter(|path| path.exists());
    if let Some(exe) = bundled_exe {
        let mut cmd = Command::new(exe);
        cmd.args(["--port", &port.to_string(), "--token", token, "--home", &home.to_string_lossy(),
                  "--static-dir", &static_dir.to_string_lossy()]);
        hide_console(&mut cmd);
        return cmd.stdout(out).stderr(err).spawn().ok();
    }
    let bundled = resource_dir.map(|dir| dir.join("aoc-core").join("main.py"))
        .filter(|path| path.exists());
    let script = bundled.unwrap_or_else(|| dev_root().join("apps").join("aoc-core").join("main.py"));
    if !script.exists() {
        eprintln!("aoc-core/main.py not found: {}", script.display());
        return None;
    }
    let mut cmd = Command::new("python");
    cmd.arg("-X")
        .arg("utf8")
        .arg(script)
        .args(["--port", &port.to_string(), "--token", token, "--home", &home.to_string_lossy(),
               "--static-dir", &static_dir.to_string_lossy()]);
    hide_console(&mut cmd);
    cmd.stdout(out).stderr(err).spawn().ok()
}

fn spawn_simlink(token: &str, home: &PathBuf, resource_dir: Option<&PathBuf>,
                 log_dir: &Path) -> Option<Child> {
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
    let (out, err) = log_stdio(log_dir, "simlink.log");
    let mut cmd = Command::new(exe);
    cmd.args(["--port", "0", "--token", token, "--home", &home.to_string_lossy()]);
    hide_console(&mut cmd);
    cmd.stdout(out).stderr(err).spawn().ok()
}

fn kill_children(app: &tauri::AppHandle) {
    if let Some(children) = app.try_state::<Children>() {
        if let Ok(mut list) = children.0.lock() {
            for child in list.iter_mut() {
                let _ = child.kill();
                let _ = child.wait();
            }
            list.clear();
        }
    }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn main() {
    // 单实例：端口被占用说明已有实例在跑，直接退出（不重复起 aoc-core / aoc-simlink）
    let _instance = match TcpListener::bind(("127.0.0.1", INSTANCE_PORT)) {
        Ok(listener) => listener,
        Err(_) => {
            eprintln!("AOC 已在运行，退出本次启动");
            return;
        }
    };

    tauri::Builder::default()
        .setup(|app| {
            let home = home_dir();
            std::fs::create_dir_all(&home).ok();
            let log_dir = home.join("logs");
            std::fs::create_dir_all(&log_dir).ok();
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
            match spawn_core(port, &token, &home, &static_dir, resource_dir.as_ref(), &log_dir) {
                Some(child) => children.push(child),
                None => eprintln!("failed to spawn aoc-core"),
            }
            if let Some(child) = spawn_simlink(&simlink_token, &home, resource_dir.as_ref(), &log_dir) {
                children.push(child);
            } else {
                eprintln!("aoc-simlink not found; telemetry disabled until built");
            }
            app.manage(Children(Mutex::new(children)));

            // -- 托盘 ------------------------------------------------------
            let open_item = MenuItem::with_id(app, "open", "打开客户端", true, None::<&str>)?;
            let logs_item = MenuItem::with_id(app, "logs", "打开日志目录", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_item, &logs_item, &quit_item])?;
            let logs_for_menu = log_dir.clone();
            let mut tray = TrayIconBuilder::with_id("aoc-main")
                .menu(&menu)
                .tooltip("AOC · 模拟飞行运行中心")
                .on_menu_event(move |app, event| match event.id().as_ref() {
                    "open" => show_main(app),
                    "logs" => {
                        let _ = Command::new("explorer")
                            .arg(logs_for_menu.as_os_str())
                            .spawn();
                    }
                    "quit" => {
                        kill_children(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;

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
            // 关闭窗口 = 最小化到托盘（P-11）；退出走托盘菜单，退出时结束两个 sidecar。
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error running AOC client");
}
