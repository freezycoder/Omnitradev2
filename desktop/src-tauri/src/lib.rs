//! OmniTrade desktop shell.
//!
//! Responsibilities:
//! * pick a free local port,
//! * launch the bundled FastAPI backend (PyInstaller binary) as a managed child
//!   process, pointed at a per-user writable data directory,
//! * inject the resolved API base URL into the webview so the static frontend can
//!   reach the backend on its dynamic port,
//! * health-check the backend and log its output,
//! * gracefully stop the backend on shutdown,
//! * read/write the user's API keys and restart the backend to apply them.

use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// Managed process + configuration for the bundled backend.
struct BackendState {
    child: Mutex<Option<Child>>,
    port: u16,
    data_dir: PathBuf,
    log_dir: PathBuf,
    backend_exe: PathBuf,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
struct Settings {
    finnhub_api_key: String,
    fred_api_key: String,
    sec_edgar_user_agent: String,
}

#[derive(Debug, Serialize)]
struct BackendStatus {
    port: u16,
    healthy: bool,
    data_dir: String,
    log_dir: String,
}

/// Ask the OS for an unused TCP port on the loopback interface.
fn find_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8788)
}

/// Locate the bundled backend executable inside the app's resource directory.
fn backend_executable(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("could not resolve resource dir: {e}"))?;
    let exe_name = if cfg!(windows) {
        "omnitrade-backend.exe"
    } else {
        "omnitrade-backend"
    };
    let candidate = resource_dir
        .join("backend")
        .join("omnitrade-backend")
        .join(exe_name);
    if candidate.exists() {
        Ok(candidate)
    } else {
        Err(format!(
            "backend executable not found at {}",
            candidate.display()
        ))
    }
}

/// Spawn the backend process, redirecting stdout/stderr to a rotating log file.
fn spawn_backend(state: &BackendState) -> Result<Child, String> {
    fs::create_dir_all(&state.log_dir).ok();
    fs::create_dir_all(&state.data_dir).ok();
    let log_path = state.log_dir.join("backend.log");
    let stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("could not open backend log: {e}"))?;
    let stderr = stdout
        .try_clone()
        .map_err(|e| format!("could not clone log handle: {e}"))?;

    let mut cmd = Command::new(&state.backend_exe);
    cmd.arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(state.port.to_string())
        .env("OMNITRADE_DATA_DIR", &state.data_dir)
        .env("OMNITRADE_WRITE_MODE", "local")
        // Let the backend self-terminate if this shell dies abnormally.
        .env("OMNITRADE_PARENT_PID", std::process::id().to_string())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr));

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd.spawn().map_err(|e| format!("failed to start backend: {e}"))
}

/// Minimal dependency-free HTTP health probe against `/api/health`.
fn http_health_ok(port: u16) -> bool {
    let addr: SocketAddr = match format!("127.0.0.1:{port}").parse() {
        Ok(a) => a,
        Err(_) => return false,
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(600)) else {
        return false;
    };
    stream
        .set_read_timeout(Some(Duration::from_millis(2000)))
        .ok();
    stream
        .set_write_timeout(Some(Duration::from_millis(2000)))
        .ok();
    let request = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    response.contains("200 OK") && response.contains("\"status\":\"ok\"")
}

fn wait_for_health(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if http_health_ok(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

/// Stop the backend gracefully (SIGTERM → uvicorn clean shutdown), then force-kill
/// if it does not exit within the grace period.
fn terminate_child(child: &mut Child) {
    #[cfg(unix)]
    {
        let pid = child.id() as i32;
        unsafe {
            libc::kill(pid, libc::SIGTERM);
        }
        let start = Instant::now();
        while start.elapsed() < Duration::from_secs(5) {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
    #[cfg(not(unix))]
    {
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// `~/.config/omnitrade/secrets.env` — the exact path the backend reads for keys.
fn secrets_path() -> Option<PathBuf> {
    let home = if cfg!(windows) {
        std::env::var_os("USERPROFILE")
    } else {
        std::env::var_os("HOME")
    }?;
    Some(
        PathBuf::from(home)
            .join(".config")
            .join("omnitrade")
            .join("secrets.env"),
    )
}

fn restart_backend(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<BackendState>();
    {
        let mut guard = state.child.lock().map_err(|_| "state poisoned")?;
        if let Some(mut child) = guard.take() {
            terminate_child(&mut child);
        }
    }
    let child = spawn_backend(&state)?;
    *state.child.lock().map_err(|_| "state poisoned")? = Some(child);
    wait_for_health(state.port, Duration::from_secs(30));
    Ok(())
}

#[tauri::command]
fn get_settings() -> Result<Settings, String> {
    let Some(path) = secrets_path() else {
        return Ok(Settings::default());
    };
    if !path.exists() {
        return Ok(Settings::default());
    }
    let content = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut settings = Settings::default();
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') || !trimmed.contains('=') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        let value = value
            .trim()
            .trim_matches('"')
            .trim_matches('\'')
            .to_string();
        match key.trim() {
            "FINNHUB_API_KEY" => settings.finnhub_api_key = value,
            "FRED_API_KEY" => settings.fred_api_key = value,
            "SEC_EDGAR_USER_AGENT" => settings.sec_edgar_user_agent = value,
            _ => {}
        }
    }
    Ok(settings)
}

#[tauri::command]
fn save_settings(app: tauri::AppHandle, settings: Settings) -> Result<(), String> {
    let Some(path) = secrets_path() else {
        return Err("could not resolve home directory".into());
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let content = format!(
        "# Managed by OmniTrade desktop. Keys are stored locally only.\n\
         FINNHUB_API_KEY={}\n\
         FRED_API_KEY={}\n\
         SEC_EDGAR_USER_AGENT=\"{}\"\n",
        settings.finnhub_api_key.trim(),
        settings.fred_api_key.trim(),
        settings.sec_edgar_user_agent.trim(),
    );
    fs::write(&path, content).map_err(|e| e.to_string())?;
    // Restart the backend so the newly saved keys are picked up.
    restart_backend(&app)?;
    Ok(())
}

#[tauri::command]
fn backend_status(state: tauri::State<BackendState>) -> BackendStatus {
    BackendStatus {
        port: state.port,
        healthy: http_health_ok(state.port),
        data_dir: state.data_dir.display().to_string(),
        log_dir: state.log_dir.display().to_string(),
    }
}

/// Open a file-system path with the OS default handler (used for logs/data dirs).
#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let program = "open";
    #[cfg(target_os = "windows")]
    let program = "explorer";
    #[cfg(all(unix, not(target_os = "macos")))]
    let program = "xdg-open";

    Command::new(program)
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

fn stop_backend(app_handle: &tauri::AppHandle) {
    if let Some(state) = app_handle.try_state::<BackendState>() {
        if let Ok(mut guard) = state.child.lock() {
            if let Some(mut child) = guard.take() {
                terminate_child(&mut child);
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_settings,
            save_settings,
            backend_status,
            open_path
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            let data_dir = handle
                .path()
                .app_data_dir()
                .map_err(|e| format!("could not resolve app data dir: {e}"))?;
            fs::create_dir_all(&data_dir).ok();

            let log_dir = handle
                .path()
                .app_log_dir()
                .map_err(|e| format!("could not resolve app log dir: {e}"))?;
            fs::create_dir_all(&log_dir).ok();

            let backend_exe = backend_executable(&handle)?;
            let port = find_free_port();

            let state = BackendState {
                child: Mutex::new(None),
                port,
                data_dir,
                log_dir,
                backend_exe,
            };
            let child = spawn_backend(&state)?;
            *state.child.lock().unwrap() = Some(child);
            app.manage(state);

            // Log backend readiness in the background (non-blocking startup).
            std::thread::spawn(move || {
                let ready = wait_for_health(port, Duration::from_secs(60));
                eprintln!(
                    "[omnitrade] backend on port {port}: {}",
                    if ready { "ready" } else { "not ready (timeout)" }
                );
            });

            // Inject the dynamic API base before any frontend code runs.
            let init_script = format!(
                "window.__OMNITRADE_API_BASE__ = \"http://127.0.0.1:{port}\";"
            );
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("OmniTrade")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1024.0, 700.0)
                .initialization_script(&init_script)
                .build()?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building OmniTrade")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                stop_backend(app_handle);
            }
        });
}
