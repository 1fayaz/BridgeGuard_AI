"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type AlertActionKind = "acknowledge-dismiss" | "approve-reject";
export type AlertStatus = "open" | "acknowledged" | "approved" | "rejected" | "dismissed";
export type AlertSource = "research" | "simulated";

export interface AlertRecord {
  id: string;
  bridgeName: string;
  severityLabel: string;
  severityBar: string;
  severityBgHex: string;
  severityTextHex: string;
  source: AlertSource;
  metric: string; // e.g. "5.79x baseline" or "85/100"
  explanationText: string;
  explanationLabel: string;
  time: string;
  actionType: AlertActionKind;
  status: AlertStatus;
  decidedAt?: string;
}

interface AlertStoreValue {
  alerts: AlertRecord[];
  openAlerts: AlertRecord[];
  handledAlerts: AlertRecord[];
  openCountFor: (bridgeName: string) => number;
  acknowledge: (id: string) => void;
  approve: (id: string) => void;
  reject: (id: string) => void;
  dismiss: (id: string) => void;
  reset: () => void;
}

const AlertStoreContext = createContext<AlertStoreValue | null>(null);

function buildSeed(seed: AlertRecord[]): AlertRecord[] {
  return seed;
}

/** One source of truth, in-memory only (reloading the page resets it - see the note on the
 * Alerts page). Real-looking records built from the research conditions and the simulated
 * truck scenario (see lib/alert-seed.ts), never a live backend. */
export function AlertStoreProvider({ seed, children }: { seed: AlertRecord[]; children: ReactNode }) {
  const [alerts, setAlerts] = useState<AlertRecord[]>(() => buildSeed(seed));

  const setStatus = useCallback((id: string, status: AlertStatus) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, status, decidedAt: new Date().toISOString() } : a)),
    );
  }, []);

  const acknowledge = useCallback((id: string) => setStatus(id, "acknowledged"), [setStatus]);
  const approve = useCallback((id: string) => setStatus(id, "approved"), [setStatus]);
  const reject = useCallback((id: string) => setStatus(id, "rejected"), [setStatus]);
  const dismiss = useCallback((id: string) => setStatus(id, "dismissed"), [setStatus]);
  const reset = useCallback(() => setAlerts(buildSeed(seed)), [seed]);

  const openAlerts = useMemo(() => alerts.filter((a) => a.status === "open"), [alerts]);
  const handledAlerts = useMemo(() => alerts.filter((a) => a.status !== "open"), [alerts]);
  const openCountFor = useCallback(
    (bridgeName: string) => openAlerts.filter((a) => a.bridgeName === bridgeName).length,
    [openAlerts],
  );

  const value: AlertStoreValue = {
    alerts,
    openAlerts,
    handledAlerts,
    openCountFor,
    acknowledge,
    approve,
    reject,
    dismiss,
    reset,
  };

  return <AlertStoreContext.Provider value={value}>{children}</AlertStoreContext.Provider>;
}

const EMPTY_STORE: AlertStoreValue = {
  alerts: [],
  openAlerts: [],
  handledAlerts: [],
  openCountFor: () => 0,
  acknowledge: () => {},
  approve: () => {},
  reject: () => {},
  dismiss: () => {},
  reset: () => {},
};

/** Returns a safe empty store (0 everywhere, no-op actions) during the brief window before the
 * seed finishes loading, instead of throwing - consumers mounted near the root (HeaderNav) render
 * before AlertStoreBoot's fetch resolves. */
export function useAlertStore(): AlertStoreValue {
  const ctx = useContext(AlertStoreContext);
  return ctx ?? EMPTY_STORE;
}
