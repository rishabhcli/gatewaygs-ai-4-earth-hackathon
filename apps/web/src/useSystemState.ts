import { useEffect, useState } from "react";
import { z } from "zod";

import {
  type HealthResponse,
  healthResponse,
  type ProductState,
  productState,
} from "./contracts";

type LoadState =
  | { phase: "loading" }
  | { phase: "ready"; health: HealthResponse; product: ProductState }
  | { phase: "degraded"; health: HealthResponse; product: ProductState }
  | { phase: "offline"; code: "API_UNREACHABLE" | "INVALID_API_RESPONSE" };

const requestTimeoutMilliseconds = 3_000;

async function fetchJson<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(path, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(requestTimeoutMilliseconds),
  });
  if (!response.ok && response.status !== 503) {
    throw new Error("API_UNREACHABLE");
  }
  return schema.parse(await response.json());
}

export function useSystemState(): LoadState {
  const [state, setState] = useState<LoadState>({ phase: "loading" });

  useEffect(() => {
    let active = true;

    async function load(): Promise<void> {
      try {
        const [health, product] = await Promise.all([
          fetchJson("/api/readyz", healthResponse),
          fetchJson("/api/v1/status", productState),
        ]);
        if (active) {
          setState({
            phase: health.status === "ready" ? "ready" : "degraded",
            health,
            product,
          });
        }
      } catch (error: unknown) {
        if (!active) return;
        setState({
          phase: "offline",
          code:
            error instanceof z.ZodError ? "INVALID_API_RESPONSE" : "API_UNREACHABLE",
        });
      }
    }

    void load();
    const interval = window.setInterval(() => void load(), 10_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  return state;
}
