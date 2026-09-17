"use client";

import { FormEvent, useState } from "react";
import { SectionHeader } from "@/components/SectionHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { setStoredAdminPassword, verifyAdminPassword } from "@/lib/api";

export function AdminAccessDenied({
  area,
  onUnlocked
}: {
  area: string;
  onUnlocked?: () => void;
}) {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUnlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password.trim()) {
      setError("Please enter the administrator password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await verifyAdminPassword(password);
      setStoredAdminPassword(password);
      if (onUnlocked) {
        onUnlocked();
      } else {
        window.location.reload();
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Authentication failed.";
      if (message.includes("401") || message.toLowerCase().includes("incorrect")) {
        setError("Incorrect administrator password.");
      } else {
        setError(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <SectionHeader title={area} badge="Admin Restricted" />
      <TerminalPanel title="Administrator Access Required" eyebrow="Restricted area">
        <div className="space-y-4 text-sm text-[var(--muted)]">
          <div className="text-base text-white">This area is restricted to administrators.</div>
          <p>
            Validation surfaces (Performance Lab, Long-Term Performance, and Calibration) are protected. Enter the
            administrator password to unlock this session, or set{" "}
            <code className="text-[var(--accent-strong)]">OMNITRADE_ADMIN=1</code> in the server environment.
          </p>

          <form onSubmit={handleUnlock} className="space-y-3 pt-2">
            <div className="flex max-w-sm gap-2">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password..."
                className="field flex-1"
                autoFocus
                disabled={submitting}
              />
              <button
                type="submit"
                className="button whitespace-nowrap"
                disabled={submitting}
              >
                {submitting ? "Checking..." : "Unlock"}
              </button>
            </div>
            {error ? (
              <div role="alert" className="text-xs text-[var(--red)]">
                {error}
              </div>
            ) : null}
          </form>
        </div>
      </TerminalPanel>
    </div>
  );
}
