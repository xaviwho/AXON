import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

import { subscribeLive } from "@/lib/ws";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface SliceState {
  eMBB: number;
  URLLC: number;
  mMTC: number;
  preempt_active: boolean;
  preempt_reason: string | null;
}

const INITIAL: SliceState = {
  eMBB: 5,
  URLLC: 5,
  mMTC: 5,
  preempt_active: false,
  preempt_reason: null,
};

export function SliceChart() {
  const [state, setState] = useState<SliceState>(INITIAL);
  const [lastEvent, setLastEvent] = useState<string | null>(null);

  useEffect(() => {
    return subscribeLive((e) => {
      if (e.event !== "slice") return;
      const p = e.payload as Record<string, unknown>;
      const st = (p["state"] ?? {}) as Record<string, unknown>;
      setState({
        eMBB:  Number(((st["eMBB"] as Record<string, unknown>)?.priority) ?? 5),
        URLLC: Number(((st["URLLC"] as Record<string, unknown>)?.priority) ?? 5),
        mMTC:  Number(((st["mMTC"] as Record<string, unknown>)?.priority) ?? 5),
        preempt_active: Boolean(st["preempt_active"]),
        preempt_reason: (st["preempt_reason"] as string | null) ?? null,
      });
      const evtName = String(p["event"] ?? "");
      if (evtName && evtName !== "snapshot") setLastEvent(evtName);
    });
  }, []);

  const data = [
    { slice: "eMBB",  priority: state.eMBB,  fill: "#1e3a8a" },
    { slice: "URLLC", priority: state.URLLC, fill: "#22c55e" },
    { slice: "mMTC",  priority: state.mMTC,  fill: "#f59e0b" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>HFR Ieum 5G+ slice priorities</CardTitle>
        {state.preempt_active ? (
          <Badge variant="danger">PREEMPT — {state.preempt_reason ?? "active"}</Badge>
        ) : (
          <Badge variant="muted">{lastEvent ?? "steady"}</Badge>
        )}
      </CardHeader>
      <CardBody>
        <div className="h-44">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="slice" tick={{ fontSize: 12, fill: "#475569" }} />
              <YAxis
                domain={[0, 10]}
                tick={{ fontSize: 12, fill: "#475569" }}
                allowDecimals={false}
              />
              <Tooltip cursor={{ fill: "rgba(30,58,138,0.06)" }} />
              <Bar dataKey="priority" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-slate-500">
          <div>eMBB &nbsp;<span className="font-medium tabular-nums text-slate-800">{state.eMBB}</span> / 10</div>
          <div>URLLC <span className="font-medium tabular-nums text-slate-800">{state.URLLC}</span> / 10</div>
          <div>mMTC <span className="font-medium tabular-nums text-slate-800">{state.mMTC}</span> / 10</div>
        </div>
      </CardBody>
    </Card>
  );
}
