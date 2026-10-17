"use client";

import { useTheme } from "@/lib/hooks/useTheme";

interface ThemeToggleProps {
  className?: string;
  showLabel?: boolean;
}

export function ThemeToggle({ className = "", showLabel = false }: ThemeToggleProps) {
  const { resolvedTheme, toggleTheme, mounted } = useTheme();

  // Render a placeholder before mount to avoid hydration mismatch while preserving layout space
  if (!mounted) {
    return (
      <button
        type="button"
        disabled
        aria-label="Toggle light or dark theme"
        className={`inline-flex items-center gap-1.5 rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2.5 py-1 text-xs font-medium text-[var(--cc-text)] opacity-60 ${className}`}
      >
        <span aria-hidden="true" className="text-sm">🌓</span>
        {showLabel && <span>Theme</span>}
      </button>
    );
  }

  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? "light" : "dark"} theme (currently ${isDark ? "dark" : "light"})`}
      title={`Switch to ${isDark ? "light" : "dark"} theme (currently ${isDark ? "dark" : "light"})`}
      className={`inline-flex items-center gap-1.5 rounded-[var(--cc-radius)] border border-[var(--cc-border-strong)] bg-[var(--cc-surface)] px-2.5 py-1 text-xs font-medium text-[var(--cc-text)] hover:bg-[var(--cc-surface-2)] transition-colors cursor-pointer select-none focus-visible:outline-2 focus-visible:outline-[var(--cc-focus)] ${className}`}
    >
      <span aria-hidden="true" className="text-sm transition-transform duration-200">
        {isDark ? "☀️" : "🌙"}
      </span>
      {showLabel && (
        <span className="font-semibold">
          {isDark ? "Light" : "Dark"}
        </span>
      )}
    </button>
  );
}
