export type Engine = {
  engine_id: string;
  venue: string;
  run_mode: string;
  enabled: boolean;
  strategies: string[];
  runtime_status: string;
  symbols?: string[];
  control?: Record<string, unknown>;
};

const API_BASE = (import.meta as any).env?.VITE_API_BASE || "";
const WS_BASE = (import.meta as any).env?.VITE_WS_BASE || "";

export async function getEngines(): Promise<Engine[]> {
  const r = await fetch(`${API_BASE}/api/engines`);
  if (!r.ok) throw new Error("Failed engines fetch");
  return r.json();
}

export async function getMetrics(): Promise<Record<string, unknown>> {
  const r = await fetch(`${API_BASE}/api/system/metrics`);
  if (!r.ok) throw new Error("Failed metrics fetch");
  return r.json();
}

export async function actionEngine(engineId: string, action: "start" | "stop" | "restart"): Promise<void> {
  const r = await fetch(`${API_BASE}/api/engines/${engineId}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action })
  });
  if (!r.ok) throw new Error("Failed engine action");
}

export async function toggleStrategy(engineId: string, strategyName: string, enabled: boolean): Promise<void> {
  const r = await fetch(`${API_BASE}/api/engines/${engineId}/strategies/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_name: strategyName, enabled })
  });
  if (!r.ok) throw new Error("Failed strategy toggle");
}

export async function addStrategy(engineId: string, strategyName: string): Promise<void> {
  const r = await fetch(`${API_BASE}/api/engines/${engineId}/strategies/add`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy_name: strategyName })
  });
  if (!r.ok) throw new Error("Failed add strategy");
}

export function eventsWsUrl(): string {
  if (WS_BASE) return `${WS_BASE}/ws/events`;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${location.host}/ws/events`;
}

