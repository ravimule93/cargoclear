"use client";

import { useState, useCallback, useEffect } from "react";
import { api } from "../api";
import { toErrorEnvelope } from "../errors";
import { invalidateMetaCache, useMeta } from "./useMeta";
import type { AppMode, ExecutionModeStatus } from "../types";

export interface UseExecutionModeState {
  activeMode: AppMode;
  modeStatus: ExecutionModeStatus | null;
  loading: boolean;
  switching: boolean;
  error: string | null;
  switchMode: (newMode: AppMode) => Promise<boolean>;
  clearError: () => void;
}

export function useExecutionMode(): UseExecutionModeState {
  const { meta, loading: metaLoading, retry: metaRetry } = useMeta();
  const [modeStatus, setModeStatus] = useState<ExecutionModeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const status = await api.getMode();
      setModeStatus(status);
    } catch {
      try {
        const stored = localStorage.getItem("cargoclear_execution_mode") as AppMode | null;
        if (stored) {
          setModeStatus({
            active_mode: stored,
            configured_mode: meta?.app_mode ?? "demo",
            supported_modes: ["demo", "live"],
            live_available: false,
            credential_source: null,
            provider: "Google Cloud Vertex AI",
            model: "gemini-2.5-flash",
            region: "asia-south1",
            live_error: null,
          });
        }
      } catch {
        // ignore
      }
    } finally {
      setLoading(false);
    }
  }, [meta?.app_mode]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const activeMode: AppMode = modeStatus?.active_mode ?? meta?.app_mode ?? "demo";

  const switchMode = useCallback(
    async (newMode: AppMode): Promise<boolean> => {
      if (newMode === activeMode) return true;

      setSwitching(true);
      setError(null);

      try {
        const status = await api.setMode(newMode);
        setModeStatus(status);
        try {
          localStorage.setItem("cargoclear_execution_mode", newMode);
          document.cookie = `cargoclear_execution_mode=${newMode}; path=/; max-age=31536000; SameSite=Lax`;
        } catch {
          // LocalStorage fallback
        }
        invalidateMetaCache();
        metaRetry();
        return true;
      } catch (err: unknown) {
        const env = toErrorEnvelope(err);
        const errorMsg =
          env.message ||
          (newMode === "live"
            ? "Cannot activate Live AI Mode: Google Cloud Vertex AI credentials are not configured."
            : "Failed to switch execution mode.");
        setError(errorMsg);
        return false;
      } finally {
        setSwitching(false);
      }
    },
    [activeMode, metaRetry]
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    activeMode,
    modeStatus,
    loading: loading || metaLoading,
    switching,
    error,
    switchMode,
    clearError,
  };
}
