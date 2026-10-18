"use client";

import { useEffect, useState, useCallback } from "react";

export type Theme = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "cargoclear-theme";
const COOKIE_NAME = "cargoclear_theme";

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getStoredTheme(): Theme {
  if (typeof window === "undefined") return "system";
  try {
    const val = localStorage.getItem(STORAGE_KEY) as Theme | null;
    if (val === "light" || val === "dark" || val === "system") return val;
    const cookieMatch = document.cookie.match(new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]*)`));
    if (cookieMatch && (cookieMatch[1] === "light" || cookieMatch[1] === "dark" || cookieMatch[1] === "system")) {
      return cookieMatch[1] as Theme;
    }
  } catch {
    // Local storage access error / sandboxed iframe
  }
  return "system";
}

function applyTheme(theme: Theme): ResolvedTheme {
  if (typeof document === "undefined") return "light";
  const resolved = theme === "system" ? getSystemTheme() : theme;
  const root = document.documentElement;

  if (resolved === "dark") {
    root.classList.remove("light");
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
    root.classList.add("light");
  }

  root.setAttribute("data-theme", resolved);
  return resolved;
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("system");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const stored = getStoredTheme();
    setThemeState(stored);
    const resolved = applyTheme(stored);
    setResolvedTheme(resolved);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      if (theme === "system") {
        const resolved = applyTheme("system");
        setResolvedTheme(resolved);
      }
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [theme, mounted]);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    const resolved = applyTheme(newTheme);
    setResolvedTheme(resolved);

    try {
      localStorage.setItem(STORAGE_KEY, newTheme);
      // Persist for 1 year in cookie for SSR and zero-FOUC
      document.cookie = `${COOKIE_NAME}=${newTheme}; path=/; max-age=31536000; SameSite=Lax`;
    } catch {
      // Storage quota or restriction
    }
  }, []);

  const toggleTheme = useCallback(() => {
    // If currently dark (either explicit dark or system dark), switch to light.
    // If currently light, switch to dark.
    const next: Theme = resolvedTheme === "dark" ? "light" : "dark";
    setTheme(next);
  }, [resolvedTheme, setTheme]);

  return {
    theme,
    resolvedTheme,
    setTheme,
    toggleTheme,
    isDark: resolvedTheme === "dark",
    mounted,
  };
}
