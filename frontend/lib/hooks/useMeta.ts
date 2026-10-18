"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { toErrorEnvelope } from "../errors";
import { demoUserFromCookie } from "../session";
import type { Meta } from "../types";

export interface MetaState {
  /** null until /meta has answered (or after it failed) */
  meta: Meta | null;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

/**
 * Backend metadata (app_mode, data_source_policy). Fetched once per page load and shared between
 * components; a failed fetch is not cached so `retry` can try again.
 */
let cached: Promise<Meta> | null = null;

export function invalidateMetaCache(): void {
  cached = null;
}

function loadMeta(force: boolean): Promise<Meta> {
  if (force || cached === null) {
    cached = api.getMeta().catch((err: unknown) => {
      cached = null;
      throw err;
    });
  }
  return cached;
}

export function useMeta(): MetaState {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoading(true);
    loadMeta(attempt > 0)
      .then((value) => {
        if (cancelled) return;
        // If user is not yet populated in meta, read active session from cookie
        if (value?.app_mode === "demo" && !value.user && typeof document !== "undefined") {
          const demoUser = demoUserFromCookie(document.cookie);
          if (demoUser) value = { ...value, user: demoUser };
        }
        setMeta(value);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setMeta(null);
        setError(toErrorEnvelope(err).message);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  return { meta, loading, error, retry };
}
