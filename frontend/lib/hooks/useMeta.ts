"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { toErrorEnvelope } from "../errors";
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

function loadMeta(force: boolean): Promise<Meta> {
  if (force || cached === null) {
    cached = api.getMeta().catch((err: unknown) => {
      cached = null;
      throw err;
    });
  }
  return cached;
}

const DEFAULT_META: Meta = {
  app_mode: "live",
  data_source_policy: "live",
  pipeline_engine: "native",
  auth: {
    enabled: true,
    oauth_client_id: "448522365737-41s34pmlanitloca4vd4qesoefa060j9.apps.googleusercontent.com",
    oauth_issuer: "https://accounts.google.com",
    allowed_email_domains: ["*"],
  },
  user: null,
};

export function useMeta(): MetaState {
  const [meta, setMeta] = useState<Meta | null>(DEFAULT_META);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    loadMeta(attempt > 0)
      .then((value) => {
        if (cancelled) return;
        // If user is not yet populated in meta, read active session from cookie
        if (value && !value.user && typeof document !== "undefined") {
          const match = document.cookie.match(/(?:__session|cargoclear_session_token)=mock-jwt-([^;]+)/);
          if (match && match[1]) {
            const tokenPayload = decodeURIComponent(match[1]);
            const parts = tokenPayload.split("-");
            const role = parts.length > 1 ? parts[parts.length - 1] : "LICENSED_CHA";
            const email = parts.length > 1 ? parts.slice(0, parts.length - 1).join("-") : tokenPayload;
            const domain = email.includes("@") ? email.split("@")[1] : "customs.com";
            value = {
              ...value,
              user: {
                user_id: `usr-${email}`,
                email,
                name: email.split("@")[0].toUpperCase(),
                tenant_id: domain,
                role: role as any,
                issuer: "https://accounts.google.com",
              },
            };
          }
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
