// Tiny typed API client over the console_api REST surface.
//
// Requests go through the Vite proxy under the `/api` prefix and the
// WebSocket subscribes to `/live` on the same origin. The proxy targets
// console_api on the host. See vite.config.ts.

import { getToken } from "./auth";

const API_PREFIX = "/api";

export type ApiError = { status: number; detail: string };

async function request<T>(
  path: string,
  init?: RequestInit & { admin?: boolean },
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.admin) {
    const tok = getToken();
    if (tok) headers.set("Authorization", `Bearer ${tok}`);
  }
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const r = await fetch(`${API_PREFIX}${path}`, { ...init, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = (await r.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* fall through */
    }
    throw { status: r.status, detail } satisfies ApiError;
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

// ---- domain types --------------------------------------------------------

export interface AuditEntry {
  id: number;
  timestamp: string;
  trigger_id: string | null;
  action_id: string;
  severity: number;
  effect: "success" | "failure" | "timeout";
  agent_confidence: number;
  layer_d_trace: string;
  parameters: Record<string, unknown>;
  latency_ms: number | null;
}

export interface AuditPage {
  total: number;
  limit: number;
  offset: number;
  entries: AuditEntry[];
}

export interface IncidentSummary {
  trigger_id: string;
  timestamp: string;
  composite_score: number;
  trigger_reason: string;
}

export interface Incident {
  trigger_id: string;
  anomaly: {
    timestamp: string;
    composite_score: number;
    trigger_reason: string;
    contributing_signals: { source: string; weight: number; description?: string }[];
  } | null;
  scene: {
    timestamp: string;
    location: string;
    hazards: { hazard_type: string; severity: string; location?: string }[];
    people_present: { person_id: string; posture: string }[];
    equipment_state: { equipment_id: string; state: string }[];
    contextual_factors: Record<string, unknown>;
  } | null;
  plan: {
    timestamp: string;
    severity: number;
    confidence: number;
    rationale: string;
    actions: { action_id: string; parameters: Record<string, unknown>; requested_latency_ms: number }[];
    audit_metadata: Record<string, unknown>;
  } | null;
  audits: AuditEntry[];
}

export interface ServiceStatus {
  name: string;
  status: "ok" | "error" | "unreachable";
  latency_ms: number;
  detail: Record<string, unknown>;
}

export interface StatusResponse {
  services: ServiceStatus[];
  db: Record<string, number>;
  recent_events: { event: string; payload: Record<string, unknown> }[];
}

export interface RulesResponse {
  path: string;
  yaml: string;
  parsed: Record<string, unknown>;
}

// ---- endpoints -----------------------------------------------------------

export const api = {
  health: () => request<{ service: string; status: string }>("/health"),
  status: () => request<StatusResponse>("/status"),
  listAudit: (params: {
    severity?: number;
    action_id?: string;
    trigger_id?: string;
    limit?: number;
    offset?: number;
  }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    return request<AuditPage>(`/audit?${qs.toString()}`);
  },
  getAudit: (id: number) => request<AuditEntry>(`/audit/${id}`),
  listIncidents: (limit = 20) =>
    request<{ incidents: IncidentSummary[] }>(`/incidents?limit=${limit}`),
  getIncident: (triggerId: string) =>
    request<Incident>(`/incidents/${encodeURIComponent(triggerId)}`),
  getRules: () => request<RulesResponse>("/rules"),
  putRules: (yaml: string) =>
    request<{ status: string; reload_required: boolean }>("/rules", {
      method: "PUT",
      body: JSON.stringify({ yaml }),
      admin: true,
    }),
  login: (username: string, password: string) =>
    request<{ access_token: string; token_type: string; expires_in: number }>(
      "/auth/login.json",
      { method: "POST", body: JSON.stringify({ username, password }) },
    ),
};
