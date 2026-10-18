"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { UserIdentity } from "@/lib/types";
import { invalidateMetaCache } from "@/lib/hooks/useMeta";
import { signOut } from "@/lib/session";

interface UserMenuProps {
  user?: UserIdentity | null;
  onLogin?: (email: string) => void;
  onLogout?: () => void;
}

export function UserMenu({ user, onLogout }: UserMenuProps) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const closeOnOutsidePress = (event: PointerEvent) => {
      const details = detailsRef.current;
      if (details?.open && event.target instanceof Node && !details.contains(event.target)) {
        details.open = false;
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      const details = detailsRef.current;
      if (event.key === "Escape" && details?.open) {
        event.preventDefault();
        details.open = false;
        summaryRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

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
          className="min-h-9 rounded-[var(--cc-radius)] bg-[var(--cc-surface-2)] border border-[var(--cc-border-strong)] px-3 py-2 text-xs font-semibold text-[var(--cc-text)] hover:bg-[var(--cc-surface-3)] transition-colors cursor-pointer flex items-center gap-1 shadow-2xs"
        >
          <span>Sign in</span>
        </Link>
        <Link
          href="/auth/signin?tab=signup"
          className="min-h-9 rounded-[var(--cc-radius)] bg-[var(--cc-action)] text-white px-3 py-2 text-xs font-semibold hover:opacity-90 transition-opacity cursor-pointer flex items-center gap-1 shadow-2xs"
        >
          <span>Register</span>
        </Link>
      </div>
    );
  }

  const roleLabel = user.role.replace(/_/g, " ");

  return (
    <details ref={detailsRef} className="relative">
      <summary ref={summaryRef} aria-label={`Account menu for ${user.email}`} className="flex min-h-9 cursor-pointer list-none items-center gap-2 border-l border-[var(--cc-border)] pl-2">
        <span aria-hidden="true" className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-[var(--cc-focus)]/40 bg-[var(--cc-action)]/15 text-[10px] font-bold text-[var(--cc-focus)]">{user.email.slice(0, 2).toUpperCase()}</span>
        <span className="hidden max-w-[130px] truncate text-[11px] font-medium text-[var(--cc-text)] lg:block" title={user.email}>{user.email}</span>
        <span aria-hidden="true" className="text-[10px] text-[var(--cc-text-muted)]">⌄</span>
      </summary>
      <div className="absolute right-0 top-[calc(100%+.5rem)] z-30 w-60 rounded-lg border border-[var(--cc-border)] bg-[var(--cc-surface)] p-3 shadow-lg">
        <p className="truncate text-xs font-semibold text-[var(--cc-text)]" title={user.email}>{user.email}</p>
        <p className="mt-1 break-words text-xs text-[var(--cc-text-muted)]">{user.tenant_id} · {roleLabel}</p>
        <button type="button" onClick={handleLogout} className="cc-sign-out mt-3 min-h-9 w-full rounded-md border px-3 py-2 text-left text-xs font-semibold transition-colors">Sign out</button>
      </div>
    </details>
  );
}
