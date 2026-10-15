/**
 * Centralized application configuration for CargoClear.
 *
 * Centralizes proxy prefixes, timeouts, polling intervals, and client constants.
 */

export const APP_CONFIG = {
  appName: "CargoClear",
  version: "0.1.0",
  api: {
    proxyPrefix: "/api/proxy",
    defaultTimeoutMs: 30_000,
    streamTimeoutMs: 280_000,
    pollingIntervalMs: 2_000,
    maxReconnectAttempts: 3,
  },
  features: {
    enableDemoAgent: true,
    enableAuditLedger: true,
    enableRecompute: true,
  },
} as const;

export default APP_CONFIG;
