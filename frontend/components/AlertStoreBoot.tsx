"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AlertStoreProvider, type AlertRecord } from "@/lib/alert-store";
import { buildAlertSeed } from "@/lib/alert-seed";

/** Mounted once near the app root (see app/layout.tsx) so every page shares the same alert
 * store instance - the nav badge, Overview's per-card chips, and /alerts all read the same
 * state. Children render immediately (useAlertStore returns a safe empty store until the seed
 * loads), then the provider mounts once the 6 real seed alerts are built. */
export default function AlertStoreBoot({ children }: { children: ReactNode }) {
  const [seed, setSeed] = useState<AlertRecord[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    buildAlertSeed().then((s) => {
      if (!cancelled) setSeed(s);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!seed) return <>{children}</>;
  return <AlertStoreProvider seed={seed}>{children}</AlertStoreProvider>;
}
