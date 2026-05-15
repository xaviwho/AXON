import { useEffect, useState } from "react";
import { subscribeLive } from "@/lib/ws";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";

interface Latencies {
  scene_from_anomaly_ms: number | null;
  plan_from_scene_ms: number | null;
  dispatch_window_ms: number | null;
}

export function LatencyStrip() {
  const [lat, setLat] = useState<Latencies>({
    scene_from_anomaly_ms: null,
    plan_from_scene_ms: null,
    dispatch_window_ms: null,
  });
  const [byTrigger] = useState<Map<string, {
    anomaly_ts?: number; scene_ts?: number; plan_ts?: number;
    first_audit_ts?: number; last_audit_ts?: number;
  }>>(() => new Map());

  useEffect(() => {
    function record() {
      // Compute latest deltas across triggers we've seen.
      const buckets = Array.from(byTrigger.values()).reverse();
      const sceneLat = buckets.find(
        (b) => b.anomaly_ts !== undefined && b.scene_ts !== undefined,
      );
      const planLat = buckets.find(
        (b) => b.scene_ts !== undefined && b.plan_ts !== undefined,
      );
      const dispLat = buckets.find(
        (b) =>
          b.plan_ts !== undefined &&
          b.first_audit_ts !== undefined &&
          b.last_audit_ts !== undefined,
      );
      setLat({
        scene_from_anomaly_ms:
          sceneLat && sceneLat.anomaly_ts !== undefined && sceneLat.scene_ts !== undefined
            ? sceneLat.scene_ts - sceneLat.anomaly_ts
            : null,
        plan_from_scene_ms:
          planLat && planLat.scene_ts !== undefined && planLat.plan_ts !== undefined
            ? planLat.plan_ts - planLat.scene_ts
            : null,
        dispatch_window_ms:
          dispLat && dispLat.last_audit_ts !== undefined && dispLat.plan_ts !== undefined
            ? dispLat.last_audit_ts - dispLat.plan_ts
            : null,
      });
    }

    return subscribeLive((e) => {
      if (e.event === "hello") return;
      const p = e.payload as Record<string, unknown>;
      const tid = p["trigger_id"] as string | undefined;
      const ts = p["timestamp"] as string | undefined;
      if (!tid || !ts) return;
      const t = Date.parse(ts);
      if (Number.isNaN(t)) return;
      const slot = byTrigger.get(tid) ?? {};
      if (e.event === "anomaly") slot.anomaly_ts = t;
      else if (e.event === "scene") slot.scene_ts = t;
      else if (e.event === "plan")  slot.plan_ts  = t;
      else if (e.event === "audit") {
        slot.first_audit_ts = slot.first_audit_ts === undefined
          ? t : Math.min(slot.first_audit_ts, t);
        slot.last_audit_ts = slot.last_audit_ts === undefined
          ? t : Math.max(slot.last_audit_ts, t);
      }
      byTrigger.set(tid, slot);
      record();
    });
  }, [byTrigger]);

  const Tile = ({
    label, value, budget,
  }: { label: string; value: number | null; budget: number }) => {
    const ok = value !== null && value <= budget;
    return (
      <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
        <div className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
          {label}
        </div>
        <div className="mt-1 flex items-baseline gap-1">
          <span className={`text-2xl font-semibold tabular-nums ${ok ? "text-emerald-700" : value === null ? "text-slate-400" : "text-amber-700"}`}>
            {value === null ? "—" : value.toFixed(1)}
          </span>
          <span className="text-xs text-slate-400">ms</span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">budget ≤ {budget} ms</div>
      </div>
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Live latency budget</CardTitle>
        <span className="text-xs text-slate-400">last incident</span>
      </CardHeader>
      <CardBody className="grid grid-cols-3 gap-3">
        <Tile label="Anomaly → scene"      value={lat.scene_from_anomaly_ms} budget={1800} />
        <Tile label="Scene → plan"         value={lat.plan_from_scene_ms}    budget={1000} />
        <Tile label="Plan → all dispatched" value={lat.dispatch_window_ms}   budget={50} />
      </CardBody>
    </Card>
  );
}
