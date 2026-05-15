import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api, type AuditPage } from "@/lib/api";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, effectBadge, severityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const PAGE_SIZE = 25;

export default function Audit() {
  const [severity, setSeverity] = useState<string>("");
  const [actionId, setActionId] = useState<string>("");
  const [triggerId, setTriggerId] = useState<string>("");
  const [offset, setOffset] = useState(0);

  const { data, isFetching, refetch } = useQuery<AuditPage>({
    queryKey: ["audit", severity, actionId, triggerId, offset],
    queryFn: () =>
      api.listAudit({
        severity: severity === "" ? undefined : Number(severity),
        action_id: actionId || undefined,
        trigger_id: triggerId || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (prev) => prev,
    refetchInterval: 2000,
  });

  const total = data?.total ?? 0;
  const entries = data?.entries ?? [];

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <Badge variant="muted">{isFetching ? "refreshing…" : "live"}</Badge>
          </CardHeader>
          <CardBody className="flex flex-wrap items-center gap-2">
            <Input
              placeholder="severity (0..5)"
              value={severity}
              onChange={(e) => { setSeverity(e.target.value); setOffset(0); }}
              className="w-32"
            />
            <Input
              placeholder="action_id"
              value={actionId}
              onChange={(e) => { setActionId(e.target.value); setOffset(0); }}
              className="w-48"
            />
            <Input
              placeholder="trigger_id"
              value={triggerId}
              onChange={(e) => { setTriggerId(e.target.value); setOffset(0); }}
              className="w-64"
            />
            <Button variant="secondary" onClick={() => refetch()}>Refresh</Button>
            <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
              <span>{total} total</span>
              <Button
                variant="ghost"
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={offset === 0}
              >
                ← prev
              </Button>
              <Button
                variant="ghost"
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
              >
                next →
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="col-span-12">
        <Card>
          <CardBody className="p-0">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase tracking-[0.12em] text-slate-500">
                <tr>
                  <th className="px-4 py-2 text-left">when</th>
                  <th className="px-4 py-2 text-left">action</th>
                  <th className="px-4 py-2 text-left">sev</th>
                  <th className="px-4 py-2 text-left">effect</th>
                  <th className="px-4 py-2 text-left">latency</th>
                  <th className="px-4 py-2 text-left">trigger</th>
                  <th className="px-4 py-2 text-left">trace</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {entries.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                      No audit entries match the filter.
                    </td>
                  </tr>
                ) : (
                  entries.map((e) => (
                    <tr key={e.id} className="hover:bg-slate-50">
                      <td className="px-4 py-2 font-mono text-xs text-slate-500">
                        {e.timestamp.slice(11, 23)}
                      </td>
                      <td className="px-4 py-2">
                        <code className="font-semibold text-slate-800">
                          {e.action_id}
                        </code>
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={severityBadge(e.severity)}>{e.severity}</Badge>
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant={effectBadge(e.effect)}>{e.effect}</Badge>
                      </td>
                      <td className="px-4 py-2 tabular-nums text-slate-600">
                        {e.latency_ms === null ? "—" : `${e.latency_ms.toFixed(1)} ms`}
                      </td>
                      <td className="px-4 py-2">
                        {e.trigger_id ? (
                          <Link
                            to={`/incidents/${e.trigger_id}`}
                            className="text-axon-navy hover:underline"
                          >
                            {e.trigger_id.slice(0, 8)}…
                          </Link>
                        ) : "—"}
                      </td>
                      <td className="px-4 py-2 max-w-[28rem] truncate text-xs text-slate-500">
                        {e.layer_d_trace}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
