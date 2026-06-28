import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { ConsoleSnapshot } from "../api/client";
import { HealthMetricKey, HealthStrip } from "../components/HealthStrip";
import { LiveTaskTable } from "../components/LiveTaskTable";
import { ProcessCards } from "../components/ProcessCards";

export function Overview({ snapshot, onSelectTask }: { snapshot: ConsoleSnapshot; onSelectTask: (taskId: string) => void }) {
  const [selectedMetric, setSelectedMetric] = useState<HealthMetricKey>("running");
  const selectedTasks = useMemo(
    () => filterTasks(snapshot.tasks, selectedMetric),
    [snapshot.tasks, selectedMetric]
  );

  return (
    <>
      <HealthStrip snapshot={snapshot} selected={selectedMetric} onSelect={setSelectedMetric} />
      <ProcessCards
        group={selectedMetric}
        tasks={selectedTasks}
        alerts={snapshot.alerts}
        onSelectTask={onSelectTask}
      />
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

const RUNNING_STATES = new Set(["EXECUTING", "RUNNING", "VERIFYING", "CODEX_REVIEWING", "REVIEWING"]);
const QUEUED_STATES = new Set(["QUEUED", "NEW", "PLANNED", "ROUTED", "WORKTREE_CREATED", "WORKTREE_READY"]);
const FAILED_STATES = new Set(["FAILED", "FAILED_FINAL"]);
const APPROVAL_STATES = new Set(["HARD_APPROVAL_WAITING", "SOFT_APPROVAL_WAITING", "NEEDS_USER", "BLOCKED"]);

function filterTasks(tasks: ConsoleSnapshot["tasks"], metric: HealthMetricKey) {
  if (metric === "running") {
    return tasks.filter((task) => RUNNING_STATES.has(task.status));
  }
  if (metric === "queued") {
    return tasks.filter((task) => QUEUED_STATES.has(task.status));
  }
  if (metric === "failed") {
    return tasks.filter((task) => FAILED_STATES.has(task.status));
  }
  if (metric === "approval") {
    return tasks.filter((task) => APPROVAL_STATES.has(task.status));
  }
  if (metric === "cost") {
    return tasks.filter((task) => task.route.model || task.route.worker);
  }
  return [];
}
