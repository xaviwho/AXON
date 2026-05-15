import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { subscribeLive } from "@/lib/ws";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, effectBadge, severityBadge } from "@/components/ui/badge";

interface AuditTick {
  id: number;
  action_id: string;
  effect: string;
  severity: number;
  latency_ms: number | null;
  trigger_id: string | null;
  ts: string;
}

let _id = 0;

export function RecentActions() {
  const [items, setItems] = useState<AuditTick[]>([]);

  useEffect(() => {
    return subscribeLive((e) => {
      if (e.event === "audit") {
        const p = e.payload as Record<string, unknown>;
        const tick: AuditTick = {
          id: _id++,
          action_id: String(p["action_id"] ?? "?"),
          effect: String(p["effect"] ?? "?"),
          severity: Number(p["severity"] ?? 0),
          latency_ms: (p["latency_ms"] as number | null) ?? null,
          trigger_id: (p["trigger_id"] as string | null) ?? null,
          ts: String(p["timestamp"] ?? ""),
        };
        setItems((prev) => [tick, ...prev].slice(0, 12));
      } else if (e.event === "hello") {
        const snap = (e.payload.snapshot ?? []) as { event: string; payload: Record<string, unknown> }[];
        const recent = snap
          .filter((m) => m.event === "audit")
          .map((m) => {
            const p = m.payload;
            return {
              id: _id++,
              action_id: String(p["action_id"] ?? "?"),
              effect: String(p["effect"] ?? "?"),
              severity: Number(p["severity"] ?? 0),
              latency_ms: (p["latency_ms"] as number | null) ?? null,
              trigger_id: (p["trigger_id"] as string | null) ?? null,
              ts: String(p["timestamp"] ?? ""),
            } satisfies AuditTick;
          })
          .reverse()
          .slice(0, 12);
        setItems(recent);
      }
    });
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent actions</CardTitle>
        <Badge variant="muted">live</Badge>
      </CardHeader>
      <CardBody className="max-h-96 overflow-y-auto p-0">
        {items.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-slate-500">
            Awaiting first action…
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {items.map((it) => (
              <li
                key={it.id}
                className="flex items-center gap-3 px-4 py-2 text-sm"
              >
                <Badge variant={effectBadge(it.effect)}>{it.effect}</Badge>
                <Badge variant={severityBadge(it.severity)}>sev {it.severity}</Badge>
                <code className="font-semibold text-slate-800">
                  {it.action_id}
                </code>
                <span className="ml-auto tabular-nums text-xs text-slate-500">
                  {it.latency_ms !== null ? `${it.latency_ms.toFixed(1)}ms` : "—"}
                </span>
                {it.trigger_id ? (
                  <Link
                    to={`/incidents/${it.trigger_id}`}
                    className="text-xs text-axon-navy hover:underline"
                  >
                    incident →
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
