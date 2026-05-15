import { useEffect, useState } from "react";
import { subscribeLive } from "@/lib/ws";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface AnomalySample {
  score: number;
  trigger_reason: string;
  trigger_id: string;
  ts: string;
}

export function AnomalyGauge() {
  const [latest, setLatest] = useState<AnomalySample | null>(null);

  useEffect(() => {
    return subscribeLive((e) => {
      if (e.event === "anomaly") {
        const p = e.payload as Record<string, unknown>;
        setLatest({
          score: Number(p["composite_score"] ?? 0),
          trigger_reason: String(p["trigger_reason"] ?? "?"),
          trigger_id: String(p["trigger_id"] ?? ""),
          ts: String(p["timestamp"] ?? ""),
        });
      } else if (e.event === "hello") {
        const snap = (e.payload.snapshot ?? []) as { event: string; payload: Record<string, unknown> }[];
        const lastA = [...snap].reverse().find((m) => m.event === "anomaly");
        if (lastA) {
          const p = lastA.payload;
          setLatest({
            score: Number(p["composite_score"] ?? 0),
            trigger_reason: String(p["trigger_reason"] ?? "?"),
            trigger_id: String(p["trigger_id"] ?? ""),
            ts: String(p["timestamp"] ?? ""),
          });
        }
      }
    });
  }, []);

  const score = latest?.score ?? 0;
  const pct = Math.max(0, Math.min(1, score)) * 100;
  const over = score > 0.4;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Composite anomaly score</CardTitle>
        <Badge variant={over ? "danger" : "muted"}>
          threshold 0.4
        </Badge>
      </CardHeader>
      <CardBody>
        <div className="flex items-baseline gap-3">
          <span className="text-4xl font-semibold tabular-nums text-slate-900">
            {score.toFixed(2)}
          </span>
          <span className="text-sm text-slate-500">/ 1.00</span>
        </div>
        <div className="mt-3 h-2 w-full rounded-full bg-slate-100">
          <div
            className={over ? "h-2 rounded-full bg-rose-500" : "h-2 rounded-full bg-axon-navy"}
            style={{ width: `${pct}%`, transition: "width 0.3s ease" }}
          />
        </div>
        <div className="mt-3 text-xs text-slate-500">
          {latest ? (
            <>
              Last trigger reason:{" "}
              <code className="text-slate-800">{latest.trigger_reason}</code>
            </>
          ) : (
            "Awaiting first anomaly…"
          )}
        </div>
      </CardBody>
    </Card>
  );
}
