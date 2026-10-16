"use client";

import Link from "next/link";
import { UserIdentity } from "@/lib/types";
import { invalidateMetaCache } from "@/lib/hooks/useMeta";

interface UserMenuProps {
  user?: UserIdentity | null;
  onLogin?: (email: string) => void;
  onLogout?: () => void;
}

export function UserMenu({ user, onLogout }: UserMenuProps) {
  const handleLogout = () => {
    invalidateMetaCache();
    const isHttps = typeof window !== "undefined" && window.location.protocol === "https:";
    const secureFlag = isHttps ? "; Secure" : "";
    document.cookie = `__session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT${secureFlag}`;
    document.cookie = `cargoclear_session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT${secureFlag}`;
    document.cookie = `cargoclear_google_id_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT${secureFlag}`;
    document.cookie = "__session=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    document.cookie = "cargoclear_session_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    document.cookie = "cargoclear_google_id_token=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    if (onLogout) {
      onLogout();
    } else {
      window.location.href = "/api/auth/logout?returnTo=/";
    }
  };

  if (!user) {
    return (
      <div className="flex items-center gap-1.5">
        <Link
          href="/auth/signin?tab=signin"
          className="rounded-[var(--cc-radius)] bg-[var(--cc-surface-2)] border border-[var(--cc-border-strong)] px-2.5 py-1 text-xs font-semibold text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] transition-colors cursor-pointer flex items-center gap-1 shadow-2xs"
        >
          <span>👤 Sign In</span>
        </Link>
        <Link
          href="/auth/signin?tab=signup"
          className="rounded-[var(--cc-radius)] bg-[var(--cc-focus)] text-white px-2.5 py-1 text-xs font-semibold hover:opacity-90 transition-opacity cursor-pointer flex items-center gap-1 shadow-2xs"
        >
          <span>Register</span>
        </Link>
      </div>
    );
  }

  const roleLabel = user.role.replace("_", " ");

  return (
    <div className="flex items-center gap-2 pl-2 border-l border-[var(--cc-border)]">
      <div className="h-6 w-6 rounded-full bg-[var(--cc-focus)]/20 border border-[var(--cc-focus)]/40 flex items-center justify-center text-[10px] font-bold text-[var(--cc-focus)]">
        {user.email.slice(0, 2).toUpperCase()}
      </div>
      <div className="hidden sm:flex flex-col text-left">
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
      <button
        type="button"
        onClick={handleLogout}
        title="Sign out of customs workspace"
        className="text-[11px] text-[var(--cc-text-muted)] hover:text-red-500 ml-1 cursor-pointer p-1 rounded hover:bg-[var(--cc-surface-2)] transition-colors"
      >
        ↪
      </button>
    </div>
  );
}
