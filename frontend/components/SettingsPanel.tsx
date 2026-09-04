"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getBackendStatus,
  getSettings,
  isDesktopApp,
  openPath,
  saveSettings,
  type BackendStatus,
  type DesktopSettings
} from "@/lib/desktop";

const EMPTY_SETTINGS: DesktopSettings = {
  finnhub_api_key: "",
  fred_api_key: "",
  sec_edgar_user_agent: ""
};

function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<DesktopSettings>(EMPTY_SETTINGS);
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [loaded, backend] = await Promise.all([getSettings(), getBackendStatus()]);
        if (!active) return;
        setSettings(loaded);
        setStatus(backend);
      } catch (error) {
        if (active) setMessage(error instanceof Error ? error.message : "Could not load settings.");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setMessage(null);
    try {
      await saveSettings(settings);
      setMessage("Saved. The analytics service was restarted to apply your keys.");
      try {
        setStatus(await getBackendStatus());
      } catch {
        // status refresh is best-effort
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save settings.");
    } finally {
      setSaving(false);
    }
  }, [settings]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="OmniTrade settings"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg border border-[var(--line-strong)] bg-[var(--surface)] p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between border-b border-[var(--line-soft)] pb-3">
          <h2 className="font-display text-2xl uppercase tracking-[0.05em] text-[var(--text)]">Settings</h2>
          <button type="button" onClick={onClose} className="button min-h-9" aria-label="Close settings">
            Close
          </button>
        </div>

        {loading ? (
          <p className="mono text-xs text-[var(--dim)]">Loading…</p>
        ) : (
          <div className="space-y-5">
            <div>
              <div className="mono mb-2 text-[10px] uppercase tracking-[0.2em] text-[var(--dim)]">API Keys</div>
              <p className="mb-4 text-xs text-[var(--muted)]">
                Keys are optional and stored locally in your home directory. Live news, macro, and filing
                signals are enabled when their keys are present.
              </p>

              <label className="mono mb-1 block text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">
                Finnhub API key
              </label>
              <input
                type="password"
                value={settings.finnhub_api_key}
                onChange={(event) => setSettings((prev) => ({ ...prev, finnhub_api_key: event.target.value }))}
                placeholder="Finnhub news / quotes (optional)"
                className="mb-3 w-full border border-[var(--line-strong)] bg-[var(--background)] px-3 py-2 font-mono text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />

              <label className="mono mb-1 block text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">
                FRED API key
              </label>
              <input
                type="password"
                value={settings.fred_api_key}
                onChange={(event) => setSettings((prev) => ({ ...prev, fred_api_key: event.target.value }))}
                placeholder="FRED macro data (optional)"
                className="mb-3 w-full border border-[var(--line-strong)] bg-[var(--background)] px-3 py-2 font-mono text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />

              <label className="mono mb-1 block text-[10px] uppercase tracking-[0.16em] text-[var(--muted)]">
                SEC EDGAR user agent
              </label>
              <input
                type="text"
                value={settings.sec_edgar_user_agent}
                onChange={(event) => setSettings((prev) => ({ ...prev, sec_edgar_user_agent: event.target.value }))}
                placeholder="OmniTrade/1.0 you@example.com"
                className="w-full border border-[var(--line-strong)] bg-[var(--background)] px-3 py-2 font-mono text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />
            </div>

            {status ? (
              <div className="border-t border-[var(--line-soft)] pt-4">
                <div className="mono mb-2 text-[10px] uppercase tracking-[0.2em] text-[var(--dim)]">
                  Analytics Service
                </div>
                <div className="mono flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--muted)]">
                  <span>
                    Port <span className="text-[var(--accent-strong)]">{status.port}</span>
                  </span>
                  <span>
                    Status{" "}
                    <span className={status.healthy ? "text-[var(--green)]" : "text-[var(--red,#e5484d)]"}>
                      {status.healthy ? "Connected" : "Starting…"}
                    </span>
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" className="button min-h-9" onClick={() => openPath(status.data_dir)}>
                    Open data folder
                  </button>
                  <button type="button" className="button min-h-9" onClick={() => openPath(status.log_dir)}>
                    Open logs
                  </button>
                </div>
              </div>
            ) : null}

            {message ? <p className="mono text-[11px] text-[var(--muted)]">{message}</p> : null}

            <div className="flex justify-end gap-2 border-t border-[var(--line-soft)] pt-4">
              <button type="button" className="button min-h-10" onClick={onClose}>
                Cancel
              </button>
              <button
                type="button"
                className="button min-h-10 border-[var(--accent)] text-[var(--accent-strong)]"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? "Saving…" : "Save keys"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function SettingsButton() {
  const [mounted, setMounted] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Only render inside the desktop app; the web build never shows this control.
  if (!mounted || !isDesktopApp()) {
    return null;
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mono flex min-h-9 w-full items-center gap-2 border border-[var(--line-soft)] px-3 text-[10px] uppercase tracking-[0.16em] text-[var(--muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--text)]"
      >
        <svg aria-hidden="true" viewBox="0 0 20 20" className="h-3.5 w-3.5 fill-none stroke-current" strokeWidth="1.5">
          <circle cx="10" cy="10" r="3" />
          <path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M4 4l1.4 1.4M14.6 14.6L16 16M16 4l-1.4 1.4M5.4 14.6L4 16" />
        </svg>
        Settings
      </button>
      {open ? <SettingsModal onClose={() => setOpen(false)} /> : null}
    </>
  );
}
