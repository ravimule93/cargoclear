"use client";

import Link from "next/link";
import { UserIdentity } from "@/lib/types";
import { invalidateMetaCache } from "@/lib/hooks/useMeta";
import { signOut } from "@/lib/session";

interface UserMenuProps {
  user?: UserIdentity | null;
  onLogin?: (email: string) => void;
  onLogout?: () => void;
}

export function UserMenu({ user, onLogout }: UserMenuProps) {
  const handleLogout = () => {
    invalidateMetaCache();
    if (onLogout) {
      onLogout();
    } else {
      signOut();
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
    <details className="relative">
      <summary aria-label="Open account menu" className="flex cursor-pointer list-none items-center gap-2 border-l border-[var(--cc-border)] pl-2">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-[var(--cc-focus)]/40 bg-[var(--cc-focus)]/15 text-[10px] font-bold text-[var(--cc-focus)]">{user.email.slice(0, 2).toUpperCase()}</span>
        <span className="hidden max-w-[130px] truncate text-[11px] font-medium text-[var(--cc-text)] lg:block" title={user.email}>{user.email}</span>
        <span aria-hidden="true" className="text-[10px] text-[var(--cc-text-muted)]">⌄</span>
      </summary>
      <div className="absolute right-0 top-[calc(100%+.5rem)] z-30 w-60 rounded-lg border border-[var(--cc-border)] bg-[var(--cc-surface)] p-3 shadow-lg">
        <p className="truncate text-xs font-semibold text-[var(--cc-text)]" title={user.email}>{user.email}</p>
        <p className="mt-0.5 text-[10px] text-[var(--cc-text-muted)]">{user.tenant_id} · {roleLabel}</p>
        <button type="button" onClick={handleLogout} className="mt-3 w-full rounded-md border border-[var(--cc-border-strong)] px-2 py-1.5 text-left text-xs font-semibold text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)]">Sign out</button>
      </div>
    </details>
  );
}
