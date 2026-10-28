"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { DashboardData } from "./types";

const CONFIGURED_API = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "";

function apiBase(): string {
  if (CONFIGURED_API) return CONFIGURED_API;
  if (typeof window !== "undefined") {
    if (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost") {
      return "http://127.0.0.1:8000";
    }
  }
  return "";
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: "no-store", ...init });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function loadDashboard(): Promise<{
  data: DashboardData;
  live: boolean;
}> {
  const base = apiBase();
  if (base) {
    try {
      return {
        data: await fetchJson<DashboardData>(`${base}/api/dashboard`),
        live: true,
      };
    } catch {
      // The snapshot keeps the public/Vercel page useful when the local API is off.
    }
  }
  return {
    data: await fetchJson<DashboardData>("/dashboard.json"),
    live: false,
  };
}

export async function regenerateGist(): Promise<void> {
  const base = apiBase();
  if (!base) {
    throw new Error("Live API is not configured; this is a read-only snapshot.");
  }
  await fetchJson(`${base}/api/ai-gist/regenerate`, { method: "POST" });
}

export function useDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loadDashboard();
      setData(next.data);
      setLive(next.live);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return useMemo(
    () => ({ data, error, loading, refresh, liveApi: live }),
    [data, error, loading, refresh, live],
  );
}
