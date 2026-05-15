import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, type Incident } from "@/lib/api";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, effectBadge, severityBadge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

interface TimelineEvent {
  ts: number;
  iso: string;
  kind: "anomaly" | "scene" | "plan" | "audit";
  label: string;
  detail: string;
  severity?: number;
  effect?: string;
}

function buildTimeline(incident: Incident): TimelineEvent[] {
  const events: TimelineEvent[] = [];
  if (incident.anomaly) {
    events.push({
      ts: Date.parse(incident.anomaly.timestamp),
      iso: incident.anomaly.timestamp,
      kind: "anomaly",
      label: `anomaly (${incident.anomaly.trigger_reason})`,
      detail: `score ${incident.anomaly.composite_score.toFixed(2)}; signals: ${incident.anomaly.contributing_signals.map((s) => s.source).join(", ")}`,
    });
  }
  if (incident.scene) {
    events.push({
      ts: Date.parse(incident.scene.timestamp),
      iso: incident.scene.timestamp,
      kind: "scene",
      label: `scene @ ${incident.scene.location}`,
      detail: `hazards: ${incident.scene.hazards.map((h) => h.hazard_type).join(", ") || "(none)"}; ` +
              `people: ${incident.scene.people_present.length}; ` +
              `equipment: ${incident.scene.equipment_state.length}`,
    });
  }
  if (incident.plan) {
    events.push({
      ts: Date.parse(incident.plan.timestamp),
      iso: incident.plan.timestamp,
      kind: "plan",
      label: `plan (confidence ${incident.plan.confidence.toFixed(2)})`,
      severity: incident.plan.severity,
      detail: `actions: ${incident.plan.actions.map((a) => a.action_id).join(", ")}`,
    });
  }
  for (const a of incident.audits) {
    events.push({
      ts: Date.parse(a.timestamp),
      iso: a.timestamp,
      kind: "audit",
      label: a.action_id,
      detail: a.latency_ms !== null ? `${a.latency_ms.toFixed(1)} ms` : "—",
      severity: a.severity,
      effect: a.effect,
    });
  }
  events.sort((a, b) => a.ts - b.ts);
  return events;
}

export default function Replay() {
  const { triggerId = "" } = useParams<{ triggerId: string }>();
  const { data, isLoading, isError } = useQuery<Incident>({
    queryKey: ["incident", triggerId],
    queryFn: () => api.getIncident(triggerId),
    enabled: !!triggerId,
  });
  const events = useMemo(() => (data ? buildTimeline(data) : []), [data]);

  // Scrub slider: index into events; default to last event
  const [idx, setIdx] = useState(0);
  const sliderMax = Math.max(0, events.length - 1);

  if (isLoading) return <Card><CardBody>Loading incident…</CardBody></Card>;
  if (isError || !data) {
    return (
      <Card>
        <CardBody className="text-rose-700">
          Could not load incident <code>{triggerId}</code>.
        </CardBody>
      </Card>
    );
  }

  const visibleIdx = Math.min(idx, sliderMax);
  const t0 = events[0]?.ts ?? 0;
  const tEnd = events[events.length - 1]?.ts ?? t0;
  const tCursor = events[visibleIdx]?.ts ?? t0;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Card>
          <CardHeader>
            <CardTitle>
              Incident <code className="ml-2 text-axon-navy">{triggerId.slice(0, 8)}…</code>
            </CardTitle>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span>{events.length} timeline event(s)</span>
              {tEnd > t0 ? <span>· total span {(tEnd - t0).toFixed(0)} ms</span> : null}
            </div>
          </CardHeader>
          <CardBody>
            <div className="flex items-center gap-3">
              <Input
                type="range"
                min={0}
                max={sliderMax}
                value={visibleIdx}
                onChange={(e) => setIdx(Number(e.target.value))}
                className="flex-1"
              />
              <div className="w-32 tabular-nums text-right text-xs text-slate-500">
                +{(tCursor - t0).toFixed(0)} ms
              </div>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="col-span-12 lg:col-span-7">
        <Card>
          <CardHeader>
            <CardTitle>Timeline (truncated to scrub point)</CardTitle>
          </CardHeader>
          <CardBody className="p-0">
            <ol className="divide-y divide-slate-100">
              {events.slice(0, visibleIdx + 1).map((e, i) => (
                <li
                  key={`${e.iso}-${i}`}
                  className="flex items-center gap-3 px-4 py-2 text-sm"
                >
                  <span className="w-16 tabular-nums text-xs text-slate-500">
                    +{(e.ts - t0).toFixed(0)} ms
                  </span>
                  <Badge variant={
                    e.kind === "audit"   ? (effectBadge(e.effect ?? "success")) :
                    e.kind === "anomaly" ? "danger" :
                    e.kind === "plan"    ? "default" : "muted"
                  }>
                    {e.kind}
                  </Badge>
                  <span className="font-mono text-sm text-slate-800">{e.label}</span>
                  {e.severity !== undefined ? (
                    <Badge variant={severityBadge(e.severity)}>sev {e.severity}</Badge>
                  ) : null}
                  <span className="ml-auto text-xs text-slate-500">{e.detail}</span>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>
      </div>

      <div className="col-span-12 lg:col-span-5 space-y-4">
        {data.plan ? (
          <Card>
            <CardHeader>
              <CardTitle>Layer D reasoning</CardTitle>
              <Badge variant={severityBadge(data.plan.severity)}>
                sev {data.plan.severity}
              </Badge>
            </CardHeader>
            <CardBody>
              <p className="text-sm text-slate-700">{data.plan.rationale}</p>
              <div className="mt-3 text-xs text-slate-500">
                fallback:{" "}
                <code>{String(Boolean(data.plan.audit_metadata?.["fallback"]))}</code>
                {" · "}
                confidence <code>{data.plan.confidence.toFixed(2)}</code>
              </div>
            </CardBody>
          </Card>
        ) : null}
        {data.scene ? (
          <Card>
            <CardHeader>
              <CardTitle>Scene description</CardTitle>
            </CardHeader>
            <CardBody>
              <pre className="overflow-x-auto rounded bg-slate-50 p-3 text-xs text-slate-700">
                {JSON.stringify(data.scene, null, 2)}
              </pre>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </div>
  );
}
