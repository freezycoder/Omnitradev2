// Thin, SSR-safe bridge to the Tauri desktop shell. On the web these helpers are
// inert (the global `__TAURI__` object is only injected inside the desktop app,
// which is created with `withGlobalTauri: true`).

type InvokeFn = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

export type DesktopSettings = {
  finnhub_api_key: string;
  fred_api_key: string;
  sec_edgar_user_agent: string;
};

export type BackendStatus = {
  port: number;
  healthy: boolean;
  data_dir: string;
  log_dir: string;
};

function getInvoke(): InvokeFn | null {
  if (typeof window === "undefined") return null;
  const tauri = (window as unknown as { __TAURI__?: { core?: { invoke?: InvokeFn } } }).__TAURI__;
  return tauri?.core?.invoke ?? null;
}

export function isDesktopApp(): boolean {
  return getInvoke() !== null;
}

export async function getSettings(): Promise<DesktopSettings> {
  const invoke = getInvoke();
  if (!invoke) throw new Error("Desktop bridge unavailable");
  return invoke<DesktopSettings>("get_settings");
}

export async function saveSettings(settings: DesktopSettings): Promise<void> {
  const invoke = getInvoke();
  if (!invoke) throw new Error("Desktop bridge unavailable");
  await invoke<void>("save_settings", { settings });
}

export async function getBackendStatus(): Promise<BackendStatus> {
  const invoke = getInvoke();
  if (!invoke) throw new Error("Desktop bridge unavailable");
  return invoke<BackendStatus>("backend_status");
}

export async function openPath(path: string): Promise<void> {
  const invoke = getInvoke();
  if (!invoke) throw new Error("Desktop bridge unavailable");
  await invoke<void>("open_path", { path });
}
