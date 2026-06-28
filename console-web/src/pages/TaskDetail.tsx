import { useEffect, useState } from "react";
import { RotateCcw, XCircle } from "lucide-react";
import { api, TaskDetail as TaskDetailData } from "../api/client";
import { RouteDecisionCard } from "../components/RouteDecisionCard";
import { TaskTimeline } from "../components/TaskTimeline";

export function TaskDetail({ taskId }: { taskId: string }) {
  const [detail, setDetail] = useState<TaskDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.taskDetail(taskId).then(setDetail).catch((err) => setError(err.message));
  }, [taskId]);

  if (error) return <section className="panel danger">{error}</section>;
  if (!detail) return <section className="panel">Loading task...</section>;

  return (
    <div className="detail-grid">
      <section className="panel">
        <div className="panel-head">
          <h2>{detail.task.task_id}</h2>
          <div className="actions">
            <button title="Cancel task" onClick={() => void api.cancelTask(detail.task.task_id)}><XCircle size={16} /></button>
            <button title="Retry task" onClick={() => void api.retryTask(detail.task.task_id)}><RotateCcw size={16} /></button>
          </div>
        </div>
        <p>{detail.task.user_goal}</p>
        <span className={`status ${detail.task.status.toLowerCase()}`}>{detail.task.status}</span>
      </section>
      <RouteDecisionCard route={detail.route_decision} />
      <section className="panel">
        <h2>Timeline</h2>
        <TaskTimeline events={detail.timeline} />
      </section>
      <section className="panel">
        <h2>Verify</h2>
        <pre>{JSON.stringify(detail.verify ?? {}, null, 2)}</pre>
      </section>
      <section className="panel">
        <h2>Review</h2>
        <pre>{JSON.stringify(detail.review ?? {}, null, 2)}</pre>
      </section>
      <section className="panel">
        <h2>Artifacts</h2>
        <div className="artifact-list">
          {detail.artifacts.map((artifact) => <a href={artifact.url} key={artifact.path}>{artifact.path}</a>)}
        </div>
      </section>
    </div>
  );
}

