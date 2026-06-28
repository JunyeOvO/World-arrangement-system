import { ArrowRight, Box, Clock3 } from "lucide-react";
import { Alert, TaskSummary } from "../api/client";
import { HealthMetricKey } from "./HealthStrip";

const GROUP_TITLES: Record<HealthMetricKey, string> = {
  running: "Running Codex Processes",
  queued: "Queued Codex Processes",
  failed: "Failed Codex Processes",
  approval: "Approval Waiting",
  alerts: "Open Alerts",
  cost: "Cost Related Processes"
};

export function ProcessCards({
  group,
  tasks,
  alerts,
  onSelectTask
}: {
  group: HealthMetricKey;
  tasks: TaskSummary[];
  alerts: Alert[];
  onSelectTask: (taskId: string) => void;
}) {
  return (
    <section className="panel process-panel">
      <div className="panel-head">
        <h2>{GROUP_TITLES[group]}</h2>
        <span className="process-count">{group === "alerts" ? alerts.length : tasks.length}</span>
      </div>
      {group === "alerts" ? (
        <div className="process-grid">
          {alerts.length === 0 && <EmptyProcessState />}
          {alerts.map((alert) => (
            <article className="process-card alert-card" key={alert.alert_id}>
              <div className="process-card-top">
                <span className={`status ${alert.severity.toLowerCase()}`}>{alert.severity}</span>
                <small>{alert.status}</small>
              </div>
              <strong>{alert.title}</strong>
              <p>{alert.message}</p>
              {alert.task_id && (
                <button type="button" onClick={() => onSelectTask(alert.task_id as string)}>
                  Open linked task <ArrowRight size={14} />
                </button>
              )}
            </article>
          ))}
        </div>
      ) : (
        <div className="process-grid">
          {tasks.length === 0 && <EmptyProcessState />}
          {tasks.map((task) => (
            <article className="process-card" key={task.task_id}>
              <div className="process-card-top">
                <span className={`status ${task.status.toLowerCase()}`}>{task.status}</span>
                <small>{task.runtime?.stale ? "stale status" : task.project_id}</small>
              </div>
              <strong>{task.user_goal || "Codex task"}</strong>
              <p>{task.task_id}</p>
              <dl>
                <dt>Worker</dt>
                <dd>{task.route.worker || "pending"}</dd>
                <dt>Model</dt>
                <dd>{task.route.model || "pending"}</dd>
                <dt>Variant</dt>
                <dd>{task.route.variant || "default"}</dd>
              </dl>
              <div className="process-card-foot">
                <span><Clock3 size={13} /> {task.updated_at}</span>
                <button type="button" onClick={() => onSelectTask(task.task_id)}>
                  Detail <ArrowRight size={14} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function EmptyProcessState() {
  return (
    <div className="empty-process">
      <Box size={20} />
      <span>No matching Codex process</span>
    </div>
  );
}
