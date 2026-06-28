import { TaskSummary } from "../api/client";

export function LiveTaskTable({ tasks, onSelect }: { tasks: TaskSummary[]; onSelect: (taskId: string) => void }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Task</th>
            <th>Route</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.task_id} onClick={() => onSelect(task.task_id)}>
              <td><span className={`status ${task.status.toLowerCase()}`}>{task.status}</span></td>
              <td>
                <strong>{task.task_id}</strong>
                <small>{task.user_goal}</small>
              </td>
              <td>{[task.route.worker, task.route.model, task.route.variant].filter(Boolean).join(" / ")}</td>
              <td>{task.updated_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

