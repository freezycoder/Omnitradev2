use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::Manager;

const API_HOST: &str = "127.0.0.1";
const API_PORT: u16 = 8788;
const FRONTEND_PORT: u16 = 3000;
const APP_URL: &str = "http://127.0.0.1:3000/overview";

struct Runtime {
    children: Mutex<Vec<Child>>,
}

impl Runtime {
    fn new() -> Self {
        Self {
            children: Mutex::new(Vec::new()),
        }
    }

    fn push(&self, child: Child) {
        if let Ok(mut children) = self.children.lock() {
            children.push(child);
        }
    }

    fn shutdown(&self) {
        if let Ok(mut children) = self.children.lock() {
            for child in children.iter_mut() {
                #[cfg(unix)]
                {
                    let pid = child.id();
                    let _ = Command::new("kill")
                        .args(["-TERM", &format!("-{pid}")])
                        .status();
                }
                let _ = child.kill();
                let _ = child.wait();
            }
            children.clear();
        }
    }
}

impl Drop for Runtime {
    fn drop(&mut self) {
        self.shutdown();
    }
}

pub fn is_repo_root(path: &Path) -> bool {
    path.join("run_api.sh").is_file() && path.join("frontend").is_dir() && path.join("api").is_dir()
}

pub fn find_repo_root() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("OMNITRADE_ROOT") {
        let path = PathBuf::from(value);
        if is_repo_root(&path) {
            return Ok(path);
        }
        return Err(format!(
            "OMNITRADE_ROOT is set to {} but that folder is not an OmniTrade repo.",
            path.display()
        ));
    }

    let compile_time = PathBuf::from(env!("OMNITRADE_REPO_ROOT"));
    if is_repo_root(&compile_time) {
        return Ok(compile_time);
    }

    if let Some(home) = std::env::var_os("HOME").map(PathBuf::from) {
        for candidate in [
            home.join("Omnitradev2"),
            home.join("omnitradev2"),
            home.join("OmniTrade"),
            home.join("omnitrade"),
        ] {
            if is_repo_root(&candidate) {
                return Ok(candidate);
            }
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        for ancestor in exe.ancestors() {
            if is_repo_root(ancestor) {
                return Ok(ancestor.to_path_buf());
            }
        }
    }

    Err(
        "Could not find the OmniTrade source folder. Keep the git repo at ~/Omnitradev2, or set OMNITRADE_ROOT to that folder."
            .to_string(),
    )
}

pub fn allow_navigation(url: &url::Url) -> bool {
    match url.scheme() {
        "tauri" | "asset" | "ipc" | "data" | "blob" => true,
        "http" | "https" => matches!(
            url.host_str(),
            Some("127.0.0.1")
                | Some("localhost")
                | Some("tauri.localhost")
                | Some("asset.localhost")
                | Some("ipc.localhost")
        ),
        _ => false,
    }
}

fn port_open(host: &str, port: u16) -> bool {
    let Ok(addr) = format!("{host}:{port}").parse() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(400)).is_ok()
}

fn wait_for_port(host: &str, port: u16, timeout: Duration) -> bool {
    let started = Instant::now();
    while started.elapsed() < timeout {
        if port_open(host, port) {
            return true;
        }
        thread::sleep(Duration::from_millis(400));
    }
    false
}

fn spawn_child(mut command: Command) -> Result<Child, String> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    command.spawn().map_err(|error| {
        format!(
            "Failed to start {}: {error}",
            command.get_program().to_string_lossy()
        )
    })
}

fn start_api(repo: &Path, runtime: &Runtime) -> Result<(), String> {
    if port_open(API_HOST, API_PORT) {
        return Ok(());
    }
    let uvicorn = repo.join(".venv/bin/uvicorn");
    if !uvicorn.is_file() {
        return Err(format!(
            "Python environment missing. In Terminal run:\ncd {}\npython3 -m venv .venv\n.venv/bin/pip install -r requirements.txt",
            repo.display()
        ));
    }
    let mut command = Command::new(uvicorn);
    command
        .current_dir(repo)
        .args([
            "api.main:app",
            "--host",
            API_HOST,
            "--port",
            &API_PORT.to_string(),
        ])
        .env("ENV", "development")
        .env("OMNITRADE_WRITE_MODE", "local");
    runtime.push(spawn_child(command)?);
    if !wait_for_port(API_HOST, API_PORT, Duration::from_secs(40)) {
        return Err("The OmniTrade API did not start on port 8788.".to_string());
    }
    Ok(())
}

fn start_frontend(repo: &Path, runtime: &Runtime) -> Result<(), String> {
    if port_open(API_HOST, FRONTEND_PORT) {
        return Ok(());
    }
    let frontend = repo.join("frontend");
    let next_bin = frontend.join("node_modules/.bin/next");
    if !next_bin.is_file() {
        return Err(format!(
            "Frontend dependencies missing. In Terminal run:\ncd {}\nnpm install",
            frontend.display()
        ));
    }
    let mut command = Command::new(next_bin);
    command
        .current_dir(&frontend)
        .env("NEXT_PUBLIC_OMNITRADE_API_URL", "http://127.0.0.1:8788");
    if frontend.join(".next").is_dir() {
        command.args([
            "start",
            "--hostname",
            API_HOST,
            "--port",
            &FRONTEND_PORT.to_string(),
        ]);
    } else {
        command.args([
            "dev",
            "--webpack",
            "--hostname",
            API_HOST,
            "--port",
            &FRONTEND_PORT.to_string(),
        ]);
    }
    runtime.push(spawn_child(command)?);
    if !wait_for_port(API_HOST, FRONTEND_PORT, Duration::from_secs(90)) {
        return Err("The OmniTrade frontend did not start on port 3000.".to_string());
    }
    Ok(())
}

fn js_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"Unknown error\"".to_string())
}

fn boot(window: tauri::WebviewWindow, runtime: tauri::State<'_, Runtime>) {
    let runtime_error = {
        let repo = match find_repo_root() {
            Ok(path) => path,
            Err(error) => {
                let _ = window.eval(&format!("window.__omnitradeError({})", js_string(&error)));
                return;
            }
        };
        if let Err(error) = start_api(&repo, &runtime) {
            Some(error)
        } else if let Err(error) = start_frontend(&repo, &runtime) {
            Some(error)
        } else {
            None
        }
    };
    if let Some(error) = runtime_error {
        let _ = window.eval(&format!("window.__omnitradeError({})", js_string(&error)));
        return;
    }
    let _ = window.eval(&format!("window.location.replace({})", js_string(APP_URL)));
}

fn spawn_boot(app: &tauri::App) {
    let handle = app.handle().clone();
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(250));
        let Some(window) = handle.get_webview_window("main") else {
            return;
        };
        let runtime = handle.state::<Runtime>();
        boot(window, runtime);
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(Runtime::new())
        .setup(|app| {
            let window_config = app
                .config()
                .app
                .windows
                .first()
                .cloned()
                .expect("main window config");
            let _window = tauri::WebviewWindowBuilder::from_config(app, &window_config)?
                .on_navigation(allow_navigation)
                .build()?;
            spawn_boot(app);
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                window.state::<Runtime>().shutdown();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running OmniTrade");
}

#[cfg(test)]
mod tests {
    use super::{allow_navigation, is_repo_root};
    use std::fs;
    use std::path::PathBuf;

    fn repo_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|path| path.parent())
            .expect("repo root")
            .to_path_buf()
    }

    #[test]
    fn repo_root_requires_api_frontend_and_launcher() {
        let root = repo_root();
        assert!(is_repo_root(&root));

        let tmp = root.join("desktop/src-tauri/target/tmp-root-check");
        let _ = fs::remove_dir_all(&tmp);
        fs::create_dir_all(&tmp).unwrap();
        assert!(!is_repo_root(&tmp));
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn navigation_allows_local_app_and_blocks_remote() {
        let allowed = [
            "http://127.0.0.1:3000/overview",
            "http://localhost:3000/etf",
            "https://127.0.0.1:3000/",
            "tauri://localhost/index.html",
        ];
        for value in allowed {
            let url = url::Url::parse(value).unwrap();
            assert!(allow_navigation(&url), "{value}");
        }

        let blocked = url::Url::parse("https://example.com/").unwrap();
        assert!(!allow_navigation(&blocked));
    }
}
