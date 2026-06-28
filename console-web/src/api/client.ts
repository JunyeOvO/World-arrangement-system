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
  raw_status?: string;
  display_status?: string;
  big_status?: "Running" | "Queued" | "Failed" | "Approval" | "Alerts" | "Done" | "Closed";
  console_group?: "running" | "queued" | "failed" | "approval" | "alerts" | "none";
  status_note?: string;
  status_reason?: string;
  is_terminal?: boolean;
  requires_user_action?: boolean;
  updated_at: string;
  route: { worker?: string; model?: string; variant?: string };
  runtime?: { live: boolean; stale: boolean };
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

export type MetricsUsage = {
  cost_series: {
    dates: string[];
    models: string[];
    rows: Array<{ date: string; model: string; cost_usd: number }>;
  };
  calls: Array<{
    created_at: string;
    date: string;
    model: string;
    worker: string;
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens: number;
    cost_usd: number;
    task_id: string;
    attempt_no: number;
    session: string;
  }>;
};

export type MetricsEfficiency = {
  attempts: number;
  priced_attempts: number;
  missing_token_rows: number;
  reference_model: string;
  actual_cost_usd: number;
  reference_cost_usd: number;
  savings_usd: number;
  savings_pct: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  total_tokens: number;
  cache_read_ratio: number;
  codex_token_savings_measured: boolean;
  codex_token_savings_note: string;
  codex: {
    events: number;
    estimated_input_tokens: number;
    estimated_output_tokens: number;
    estimated_total_tokens: number;
    planning_dispatch_tokens: number;
    world_review_tokens: number;
    actual_codex_review_tokens: number;
    actual_codex_event_count: number;
    measured: boolean;
    estimation_method: string;
    quota_goal: {
      baseline_days: number;
      target_days: number;
      target_multiplier: number;
      required_codex_reduction_pct: number;
      max_codex_share_pct: number;
    };
  };
  by_model: Array<{
    worker: string;
    model: string;
    attempts: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_input_tokens: number;
    total_tokens: number;
    actual_cost_usd: number;
    reference_cost_usd: number;
    savings_usd: number;
  }>;
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
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function getText(path: string): Promise<string> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}

export const api = {
  snapshot: () => getJson<ConsoleSnapshot>(`/api/console/snapshot?t=${Date.now()}`),
  taskDetail: (taskId: string) => getJson<TaskDetail>(`/api/tasks/${encodeURIComponent(taskId)}`),
  taskArtifact: (taskId: string, artifactPath: string) =>
    getText(`/api/tasks/${encodeURIComponent(taskId)}/artifacts/${artifactPath}`),
  metrics: () => getJson<MetricsSummary>("/api/metrics/summary"),
  metricsUsage: () => getJson<MetricsUsage>("/api/metrics/usage?limit=200"),
  metricsEfficiency: () => getJson<MetricsEfficiency>("/api/metrics/efficiency"),
  models: () => getJson<{ models: ModelMetric[] }>("/api/metrics/models"),
  audit: () => getJson<{ events: TimelineEvent[] }>("/api/audit?limit=100"),
  cancelTask: (taskId: string) => postJson(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { reason: "console cancel" }),
  retryTask: (taskId: string) => postJson(`/api/tasks/${encodeURIComponent(taskId)}/retry`, {}),
  dismissTask: (taskId: string) => postJson(`/api/tasks/${encodeURIComponent(taskId)}/dismiss`, { reason: "dismissed from console process card" }),
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
