import { useEffect, useState } from "react";
import { RotateCcw, XCircle } from "lucide-react";
import { api, TaskDetail as TaskDetailData } from "../api/client";
import { RouteDecisionCard } from "../components/RouteDecisionCard";
import { TaskTimeline } from "../components/TaskTimeline";

export function TaskDetail({ taskId }: { taskId: string }) {
  const [detail, setDetail] = useState<TaskDetailData | null>(null);
  const [output, setOutput] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [outputError, setOutputError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setOutput("");
    setOutputError(null);
    api.taskDetail(taskId)
      .then((payload) => {
        setDetail(payload);
        const hasFinal = payload.artifacts.some((artifact) => artifact.path === "final.md");
        if (!hasFinal) {
          setOutputError("No final output recorded yet.");
          return;
        }
        api.taskArtifact(taskId, "final.md")
          .then(setOutput)
          .catch((err) => setOutputError(err.message));
      })
      .catch((err) => setError(err.message));
  }, [taskId]);

  if (error) return <section className="panel danger">{error}</section>;
  if (!detail) return <section className="panel">Loading task...</section>;

  const visibleStatus = detail.task.display_status || detail.task.status;

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
        <span className={`status ${visibleStatus.toLowerCase()}`}>{visibleStatus}</span>
        {detail.task.status_note && <small>{detail.task.status_note}</small>}
        {detail.task.display_status && detail.task.display_status !== detail.task.status && (
          <small>Raw state: {detail.task.status}</small>
        )}
      </section>
      <RouteDecisionCard route={detail.route_decision} />
      <section className="panel">
        <h2>Timeline</h2>
        <TaskTimeline events={detail.timeline} />
      </section>
      <section className="panel output-panel">
        <h2>Output</h2>
        {output ? <pre>{output}</pre> : <p>{outputError || "Loading output..."}</p>}
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
