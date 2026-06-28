import { AlertTriangle } from "lucide-react";
import { ConsoleSnapshot } from "../api/client";
import { HealthStrip } from "../components/HealthStrip";
import { LiveTaskTable } from "../components/LiveTaskTable";

export function Overview({ snapshot, onSelectTask }: { snapshot: ConsoleSnapshot; onSelectTask: (taskId: string) => void }) {
  return (
    <>
      <HealthStrip snapshot={snapshot} />
      {snapshot.alerts.length > 0 && (
        <section className="alerts">
          {snapshot.alerts.map((alert) => (
            <article key={alert.alert_id}>
              <AlertTriangle size={18} />
              <div>
                <strong>{alert.severity.toUpperCase()} · {alert.title}</strong>
                <small>{alert.message}</small>
              </div>
            </article>
          ))}
        </section>
      )}
      <section className="panel">
        <h2>Live Tasks</h2>
        <LiveTaskTable tasks={snapshot.tasks} onSelect={onSelectTask} />
      </section>
    </>
  );
}

