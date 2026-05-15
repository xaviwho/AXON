import { ServiceGrid } from "@/components/dashboard/ServiceGrid";
import { AnomalyGauge } from "@/components/dashboard/AnomalyGauge";
import { SliceChart } from "@/components/dashboard/SliceChart";
import { RecentActions } from "@/components/dashboard/RecentActions";
import { LatencyStrip } from "@/components/dashboard/LatencyStrip";

export default function Dashboard() {
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <ServiceGrid />
      </div>

      <div className="col-span-12 lg:col-span-4">
        <AnomalyGauge />
      </div>
      <div className="col-span-12 lg:col-span-4">
        <SliceChart />
      </div>
      <div className="col-span-12 lg:col-span-4">
        <LatencyStrip />
      </div>

      <div className="col-span-12">
        <RecentActions />
      </div>
    </div>
  );
}
