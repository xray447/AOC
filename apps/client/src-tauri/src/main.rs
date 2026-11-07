// AOC Tauri 外壳：拉起 aoc-core 与 aoc-simlink，随机端口 + token，再让窗口指向本地 SPA。
// 生产构建不弹控制台窗口（CREATE_NO_WINDOW），子进程日志写 %LOCALAPPDATA%\AOC\logs；
// 关闭主窗口只最小化到托盘，托盘菜单可打开客户端 / 日志目录 / 退出（P-11 / A-32）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs::OpenOptions,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};
use serde_json::Value;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, WindowEvent};
use tauri_plugin_notification::NotificationExt;

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

/// 极简本机 HTTP 客户端（docs/12 §6：Rust 侧轮询 `/local/notifications`）。
///
/// 只连 127.0.0.1、只发 GET/POST JSON，不引 reqwest —— 打包体积与编译时间都省下来。
/// 请求用 HTTP/1.0，避免 uvicorn 回 chunked 响应还要自己解块。
fn aoc_http(port: u16, token: &str, method: &str, path: &str, body: Option<&str>) -> Option<String> {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(5)));
    let payload = body.unwrap_or("");
    let request = format!(
        "{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nX-AOC-Token: {token}\r\n\
         Content-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{payload}",
        payload.len()
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = Vec::new();
    stream.read_to_end(&mut raw).ok()?;
    let text = String::from_utf8_lossy(&raw).to_string();
    let (_, response_body) = text.split_once("\r\n\r\n")?;
    Some(response_body.to_string())
}

/// 置顶迷你浮窗（docs/12 §6.3.2 / Q-10 ②）：无边框 + 透明 + always_on_top，
/// 页面用的是同一份前端 bundle 的 `?overlay=1` 视图。首次需要时才创建。
fn ensure_overlay(app: &tauri::AppHandle, port: u16) -> Option<tauri::WebviewWindow> {
    if let Some(window) = app.get_webview_window("stand-overlay") {
        return Some(window);
    }
    let url: tauri::Url = format!("http://127.0.0.1:{port}/?overlay=1").parse().ok()?;
    tauri::WebviewWindowBuilder::new(app, "stand-overlay", tauri::WebviewUrl::External(url))
        .title("AOC 到达提醒")
        .inner_size(340.0, 176.0)
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .focused(false)
        .visible(false)
        .shadow(false)
        .build()
        .ok()
}

fn show_overlay(app: &tauri::AppHandle, port: u16) {
    let handle = app.clone();
    // 窗口创建要走主线程；创建后 3 分钟自动收起（机位看一眼就够）
    let _ = app.run_on_main_thread(move || {
        if let Some(window) = ensure_overlay(&handle, port) {
            let _ = window.show();
            let hide = window.clone();
            thread::spawn(move || {
                thread::sleep(Duration::from_secs(180));
                let _ = hide.hide();
            });
        }
    });
}

/// 到达提醒的常驻消费者：系统通知 + 置顶浮窗，ack 之后前端不会重复弹。
fn spawn_notice_watcher(app: tauri::AppHandle, port: u16, token: String) {
    thread::spawn(move || {
        let mut cursor: u64 = 0;
        let mut notice_on = true;
        let mut overlay_on = true;
        let mut tick: u32 = 0;
        loop {
            thread::sleep(Duration::from_secs(10));
            if tick % 6 == 0 {
                if let Some(text) = aoc_http(port, &token, "GET", "/local/settings", None) {
                    if let Ok(value) = serde_json::from_str::<Value>(&text) {
                        if let Some(settings) = value.get("settings") {
                            notice_on = settings
                                .get("stand_notice")
                                .and_then(Value::as_bool)
                                .unwrap_or(true);
                            overlay_on = settings
                                .get("stand_show_overlay")
                                .and_then(Value::as_bool)
                                .unwrap_or(true);
                        }
                    }
                }
            }
            tick = tick.wrapping_add(1);
            if !notice_on {
                continue;
            }
            let path = format!("/local/notifications?since={cursor}");
            let Some(text) = aoc_http(port, &token, "GET", &path, None) else {
                continue; // core 还没起好 / 正在重启
            };
            let Ok(value) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            let items = value
                .get("items")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            for item in items {
                if let Some(seq) = item.get("seq").and_then(Value::as_u64) {
                    cursor = cursor.max(seq);
                }
                let title = item
                    .get("title")
                    .and_then(Value::as_str)
                    .unwrap_or("AOC 到达提醒");
                let body = item
                    .get("body")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let _ = app.notification().builder().title(title).body(body).show();
                if overlay_on {
                    show_overlay(&app, port);
                }
                if let Some(id) = item.get("id").and_then(Value::as_str) {
                    let ack = aoc_http(
                        port,
                        &token,
                        "POST",
                        &format!("/local/notifications/{id}/ack"),
                        Some("{\"by\":\"tauri\"}"),
                    );
                    if ack.is_none() {
                        eprintln!("通知 ack 失败: {id}");
                    }
                }
            }
        }
    });
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
        // docs/12：Windows 系统通知（关掉主窗口/全屏飞行时仍能弹出）
        .plugin(tauri_plugin_notification::init())
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
            let watch_app = app.handle().clone();
            let watch_token = token.clone();
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
                // docs/12 §6：到达提醒的常驻消费者（页面隐藏时也照常弹）
                spawn_notice_watcher(watch_app, port, watch_token);
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
