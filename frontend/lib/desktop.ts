// Thin, SSR-safe bridge to the Tauri desktop shell. On the web these helpers are
// inert (the global `__TAURI__` object is only injected inside the desktop app,
// which is created with `withGlobalTauri: true`).

type InvokeFn = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

export type DesktopSettings = {
  finnhub_api_key: string;
  fred_api_key: string;
  sec_edgar_user_agent: string;
  finnhub_configured?: boolean;
  fred_configured?: boolean;
  finnhub_hint?: string;
  fred_hint?: string;
};

export type BackendStatus = {
  port: number;
  healthy: boolean;
  data_dir: string;
  log_dir: string;
};

function getInvoke(): InvokeFn | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    __TAURI__?: { core?: { invoke?: InvokeFn } };
    __TAURI_INTERNALS__?: { invoke?: InvokeFn };
  };
  // `__TAURI_INTERNALS__.invoke` is always injected into a Tauri v2 webview,
  // regardless of the `withGlobalTauri` setting, so it is the most reliable path.
  return w.__TAURI_INTERNALS__?.invoke ?? w.__TAURI__?.core?.invoke ?? null;
}

export function isDesktopApp(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { isTauri?: boolean; __TAURI_INTERNALS__?: unknown };
  return w.isTauri === true || w.__TAURI_INTERNALS__ != null || getInvoke() !== null;
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
