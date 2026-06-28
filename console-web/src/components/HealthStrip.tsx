import { Activity, AlertTriangle, CircleDollarSign, Clock, ListChecks, ShieldAlert } from "lucide-react";
import { ConsoleSnapshot } from "../api/client";

export function HealthStrip({ snapshot }: { snapshot: ConsoleSnapshot }) {
  const items = [
    { label: "Running", value: snapshot.health.running, icon: Activity },
    { label: "Queued", value: snapshot.health.queued, icon: Clock },
    { label: "Failed", value: snapshot.health.failed, icon: ShieldAlert },
    { label: "Approval", value: snapshot.health.approval_waiting, icon: ListChecks },
    { label: "Alerts", value: snapshot.health.open_alerts, icon: AlertTriangle },
    { label: "Cost", value: `$${snapshot.health.cost_today_usd.toFixed(4)}`, icon: CircleDollarSign }
  ];

  return (
    <section className="health-strip">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div className="metric" key={item.label}>
            <Icon size={18} />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        );
      })}
    </section>
  );
}

