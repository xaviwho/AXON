import { useQuery } from "@tanstack/react-query";
import { api, type StatusResponse, type ServiceStatus } from "@/lib/api";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const LAYER_LABELS: Record<string, string> = {
  sensing: "L1 Sensing",
  vision: "L3a Vision (YOLOv10 + Pose)",
  fusion: "L3b Fusion",
  vlm: "L3c VLM",
  agent: "L3d Agent",
  action: "L4 Dispatcher",
  slice_control_mock: "L2 Slice Control (mock)",
  actuators_mock: "Actuators (mock)",
};

function statusVariant(s: ServiceStatus["status"]): "success" | "warning" | "danger" {
  if (s === "ok") return "success";
  if (s === "error") return "warning";
  return "danger";
}

export function ServiceGrid() {
  const { data, isError } = useQuery<StatusResponse>({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: 2000,
  });

  if (isError) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-rose-700">
            Console API unreachable. Is <code>console_api</code> running?
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Service status</CardTitle>
        <Badge variant="muted">2s poll</Badge>
      </CardHeader>
      <CardBody className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        {(data?.services ?? []).map((svc) => (
          <div
            key={svc.name}
            className="rounded-lg border border-slate-100 bg-slate-50 p-3"
          >
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium text-slate-500">
                {LAYER_LABELS[svc.name] ?? svc.name}
              </div>
              <Badge variant={statusVariant(svc.status)}>{svc.status}</Badge>
            </div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-lg font-semibold tabular-nums text-slate-800">
                {svc.latency_ms.toFixed(1)}
                <span className="ml-1 text-xs font-normal text-slate-400">ms</span>
              </span>
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
