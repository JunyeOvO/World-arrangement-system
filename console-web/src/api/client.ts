export type ConsoleSnapshot = {
  health: {
    status: string;
    running: number;
    queued: number;
    failed: number;
    approval_waiting: number;
    open_alerts: number;
    cost_today_usd: number;
  };
  tasks: TaskSummary[];
  alerts: Alert[];
  metrics: MetricsSummary;
  models: ModelMetric[];
};

export type TaskSummary = {
  task_id: string;
  project_id: string;
  user_goal: string;
  status: string;
  updated_at: string;
  route: { worker?: string; model?: string; variant?: string };
};

export type TimelineEvent = {
  id: number;
  task_id: string;
  at: string;
  event_type: string;
  from_state?: string;
  to_state?: string;
  payload: Record<string, unknown>;
};

export type TaskDetail = {
  task: TaskSummary;
  timeline: TimelineEvent[];
  route_decision?: Record<string, unknown>;
  approval?: Record<string, unknown>;
  verify?: Record<string, unknown>;
  review?: Record<string, unknown>;
  metrics: Record<string, unknown>[];
  artifacts: { path: string; name: string; url: string }[];
};

export type MetricsSummary = {
  attempts: number;
  total_cost_usd: number;
  p95_duration_ms: number;
  failure_reasons: Record<string, number>;
};

export type ModelMetric = {
  model?: string;
  worker?: string;
  attempts: number;
  avg_cost_usd?: number;
  success_rate?: number;
};

export type Alert = {
  alert_id: string;
  severity: string;
  title: string;
  message: string;
  task_id?: string;
  status: string;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  snapshot: () => getJson<ConsoleSnapshot>("/api/console/snapshot"),
  taskDetail: (taskId: string) => getJson<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`),
  metrics: () => getJson<MetricsSummary>("/api/metrics/summary"),
  models: () => getJson<{ models: ModelMetric[] }>("/api/metrics/models"),
  audit: () => getJson<{ events: TimelineEvent[] }>("/api/audit?limit=100"),
  cancelTask: (taskId: string) => postJson(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { reason: "console cancel" }),
  retryTask: (taskId: string) => postJson(`/api/tasks/${encodeURIComponent(taskId)}/retry`, {}),
  resolveAlert: (alertId: string) => postJson(`/api/alerts/${encodeURIComponent(alertId)}/resolve`, {})
};

async function postJson(path: string, body: unknown): Promise<unknown> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}
