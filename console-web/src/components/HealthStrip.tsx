import { Activity, AlertTriangle, CircleDollarSign, Clock, ListChecks, ShieldAlert } from "lucide-react";
import { ConsoleSnapshot } from "../api/client";

export type HealthMetricKey = "running" | "queued" | "failed" | "approval" | "alerts" | "cost";

export function HealthStrip({
  snapshot,
  selected,
  onSelect
}: {
  snapshot: ConsoleSnapshot;
  selected: HealthMetricKey;
  onSelect: (key: HealthMetricKey) => void;
}) {
  const items = [
    { key: "running" as const, label: "Running", value: snapshot.health.running, icon: Activity },
    { key: "queued" as const, label: "Queued", value: snapshot.health.queued, icon: Clock },
    { key: "failed" as const, label: "Failed", value: snapshot.health.failed, icon: ShieldAlert },
    { key: "approval" as const, label: "Approval", value: snapshot.health.approval_waiting, icon: ListChecks },
    { key: "alerts" as const, label: "Alerts", value: snapshot.health.open_alerts, icon: AlertTriangle },
    { key: "cost" as const, label: "Cost", value: `$${snapshot.health.cost_today_usd.toFixed(4)}`, icon: CircleDollarSign }
  ];

  return (
    <section className="health-strip" aria-label="System health filters">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            className={`metric ${selected === item.key ? "selected" : ""}`}
            key={item.label}
            onClick={() => onSelect(item.key)}
            type="button"
            aria-pressed={selected === item.key}
          >
            <Icon size={18} />
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </button>
        );
      })}
    </section>
  );
}
