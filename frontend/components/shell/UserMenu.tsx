"use client";

import { useState } from "react";
import { UserIdentity } from "@/lib/types";

interface UserMenuProps {
  user?: UserIdentity | null;
  onLogin?: (email: string) => void;
  onLogout?: () => void;
}

export function UserMenu({ user, onLogin, onLogout }: UserMenuProps) {
  const [showModal, setShowModal] = useState(false);
  const [emailInput, setEmailInput] = useState("");

  const handleSignIn = (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailInput.trim()) return;
    onLogin?.(emailInput.trim().toLowerCase());
    setShowModal(false);
  };

  if (!user) {
    return (
      <>
        <button
          type="button"
          onClick={() => setShowModal(true)}
          className="rounded-[var(--cc-radius)] bg-[var(--cc-surface-2)] border border-[var(--cc-border-strong)] px-2.5 py-1 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] transition-colors cursor-pointer flex items-center gap-1.5"
        >
          <span>👤 Sign In</span>
        </button>

        {showModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
            <div className="w-full max-w-sm rounded-lg bg-[var(--cc-surface)] border border-[var(--cc-border-strong)] p-5 shadow-xl">
              <div className="flex items-center justify-between pb-3 border-b border-[var(--cc-border)]">
                <h3 className="text-sm font-semibold text-[var(--cc-text)]">Commercial SSO Sign In</h3>
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="text-xs text-[var(--cc-text-muted)] hover:text-[var(--cc-text)]"
                >
                  ✕
                </button>
              </div>
              <p className="text-xs text-[var(--cc-text-muted)] my-3">
                Sign in with your Customs House Agent (CHA) work email (e.g. <code>customs.com</code> or <code>dhl.com</code>) to access your corporate workspace.
              </p>
              <form onSubmit={handleSignIn} className="space-y-3">
                <input
                  type="email"
                  required
                  placeholder="agent@customs.com"
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  className="w-full rounded border border-[var(--cc-border-strong)] bg-[var(--cc-surface-2)] px-3 py-1.5 text-xs text-[var(--cc-text)] focus:outline-hidden focus:ring-1 focus:ring-[var(--cc-focus)]"
                />
                <button
                  type="submit"
                  className="w-full rounded bg-[var(--cc-focus)] py-1.5 text-xs font-semibold text-white hover:opacity-90 cursor-pointer"
                >
                  Continue with Corporate SSO
                </button>
                <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-[var(--cc-border)]">
                  <span className="text-[10px] text-[var(--cc-text-muted)]">Quick demo presets:</span>
                  <button
                    type="button"
                    onClick={() => {
                      onLogin?.("demo-cha@customs.com");
                      setShowModal(false);
                    }}
                    className="text-[10px] rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
                  >
                    customs.com
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onLogin?.("agent@dhl.com");
                      setShowModal(false);
                    }}
                    className="text-[10px] rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
                  >
                    dhl.com
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onLogin?.("broker@fedex.com");
                      setShowModal(false);
                    }}
                    className="text-[10px] rounded bg-[var(--cc-surface-2)] border border-[var(--cc-border)] px-2 py-0.5 text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] cursor-pointer"
                  >
                    fedex.com
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </>
    );
  }

  const roleLabel = user.role.replace("_", " ");

  return (
    <div className="flex items-center gap-2 pl-2 border-l border-[var(--cc-border)]">
      <div className="h-6 w-6 rounded-full bg-[var(--cc-focus)]/20 border border-[var(--cc-focus)]/40 flex items-center justify-center text-[10px] font-bold text-[var(--cc-focus)]">
        {user.email.slice(0, 2).toUpperCase()}
      </div>
      <div className="flex flex-col text-left">
        <span className="text-[11px] font-medium text-[var(--cc-text)] leading-tight max-w-[130px] truncate" title={user.email}>
          {user.email}
        </span>
        <div className="flex items-center gap-1">
          <span className="text-[9px] text-[var(--cc-text-muted)] font-mono">{user.tenant_id}</span>
          <span className="text-[9px] bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-semibold px-1 py-0.2 rounded border border-emerald-500/20">
            {roleLabel}
          </span>
        </div>
      </div>
      {onLogout && (
        <button
          type="button"
          onClick={onLogout}
          title="Sign out of customs workspace"
          className="text-[11px] text-[var(--cc-text-muted)] hover:text-[var(--cc-text)] ml-1 cursor-pointer"
        >
          ↪
        </button>
      )}
    </div>
  );
}
