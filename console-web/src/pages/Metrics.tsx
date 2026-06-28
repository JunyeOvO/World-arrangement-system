import { CSSProperties, useEffect, useMemo, useState } from "react";
import { ChartColumn, CircleDollarSign, Clock3, Gauge } from "lucide-react";
import { api, ConsoleSnapshot, MetricsUsage } from "../api/client";

export function Metrics({ snapshot }: { snapshot: ConsoleSnapshot }) {
  const [usage, setUsage] = useState<MetricsUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.metricsUsage().then(setUsage).catch((err) => setError(err.message));
  }, []);

  return (
    <div className="metrics-page">
      <section className="panel metrics-summary-panel">
        <h2>Usage Summary</h2>
        <div className="summary-kpis">
          <MetricKpi label="Attempts" value={snapshot.metrics.attempts.toString()} icon={<Gauge size={18} />} />
          <MetricKpi label="Total cost" value={`$${snapshot.metrics.total_cost_usd.toFixed(4)}`} icon={<CircleDollarSign size={18} />} />
          <MetricKpi label="P95 duration" value={`${snapshot.metrics.p95_duration_ms} ms`} icon={<Clock3 size={18} />} />
        </div>
      </section>
      <ModelSummary models={snapshot.models} />
      <section className="panel metrics-wide">
        <h2>Cost by Model</h2>
        {error && <div className="banner">{error}</div>}
        <CostChart usage={usage} />
      </section>
      <section className="panel metrics-wide">
        <h2>Model Calls</h2>
        <UsageTable usage={usage} />
      </section>
    </div>
  );
}

function MetricKpi({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="summary-kpi">
      <span>{icon}</span>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function ModelSummary({ models }: { models: ConsoleSnapshot["models"] }) {
  return (
    <section className="panel model-summary-panel">
      <div className="panel-head">
        <h2>Models</h2>
        <span className="process-count">{models.length}</span>
      </div>
      <div className="compact-models">
        {models.length === 0 && <div className="compact-empty">No model metrics yet</div>}
        {models.slice(0, 4).map((model) => (
          <div className="compact-model-row" key={`${model.worker}-${model.model}`}>
            <div>
              <strong>{model.model || "unknown"}</strong>
              <small>{model.worker || "worker pending"}</small>
            </div>
            <div>
              <span>{model.attempts}</span>
              <small>{((model.success_rate ?? 0) * 100).toFixed(0)}%</small>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CostChart({ usage }: { usage: MetricsUsage | null }) {
  const chart = useMemo(() => buildChart(usage), [usage]);
  if (!usage) {
    return <div className="empty-process"><ChartColumn size={20} /><span>Loading metrics...</span></div>;
  }
  if (usage.cost_series.rows.length === 0) {
    return <div className="empty-process"><ChartColumn size={20} /><span>No cost metrics recorded yet</span></div>;
  }
  return (
    <div className="cost-chart" style={{ "--chart-max": chart.max.toString() } as CSSProperties}>
      <div className="chart-grid">
        {chart.ticks.map((tick) => (
          <div className="chart-line" key={tick} style={{ bottom: `${(tick / chart.max) * 100}%` }}>
            <span>${tick.toFixed(0)}</span>
          </div>
        ))}
        <div className="bar-groups">
          {chart.dates.map((date) => (
            <div className="bar-group" key={date}>
              <div className="bars">
                {chart.models.map((model, index) => {
                  const value = chart.values.get(`${date}:${model}`) ?? 0;
                  return (
                    <div
                      className={`bar model-${index % 4}`}
                      key={model}
                      title={`${date} ${model}: $${value.toFixed(4)}`}
                      style={{ height: `${Math.max((value / chart.max) * 100, value > 0 ? 2 : 0)}%` }}
                    />
                  );
                })}
              </div>
              <span>{formatShortDate(date)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="chart-legend">
        {chart.models.map((model, index) => (
          <span key={model}><i className={`legend-swatch model-${index % 4}`} />{model}</span>
        ))}
      </div>
    </div>
  );
}

function UsageTable({ usage }: { usage: MetricsUsage | null }) {
  if (!usage) {
    return <div className="empty-process">Loading call details...</div>;
  }
  return (
    <div className="table-wrap usage-table">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Model</th>
            <th>Input</th>
            <th>Output</th>
            <th>Cost</th>
            <th>Session</th>
          </tr>
        </thead>
        <tbody>
          {usage.calls.length === 0 && (
            <tr>
              <td colSpan={6}>No model calls recorded yet</td>
            </tr>
          )}
          {usage.calls.map((call) => (
            <tr key={`${call.task_id}-${call.attempt_no}`}>
              <td>{formatDateTime(call.created_at)}</td>
              <td><code>{call.model}</code></td>
              <td><span className="token-cell">▥</span> {call.input_tokens}</td>
              <td><span className="token-cell">▥</span> {call.output_tokens}</td>
              <td>{call.worker || "Go"} (${call.cost_usd.toFixed(4)})</td>
              <td><code>{call.session}</code></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function buildChart(usage: MetricsUsage | null) {
  const values = new Map<string, number>();
  const dates = usage?.cost_series.dates ?? [];
  const models = usage?.cost_series.models ?? [];
  let max = 0;
  for (const row of usage?.cost_series.rows ?? []) {
    values.set(`${row.date}:${row.model}`, row.cost_usd);
    max = Math.max(max, row.cost_usd);
  }
  max = Math.max(max, 1);
  const step = Math.ceil(max / 4);
  return { dates, models, values, max: step * 4, ticks: [0, step, step * 2, step * 3, step * 4] };
}

function formatShortDate(date: string) {
  if (date === "unknown") return date;
  const [, month, day] = date.split("-");
  return `${Number(month)}月 ${day}`;
}

function formatDateTime(value: string) {
  if (!value) return "unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getMonth() + 1}月${date.getDate()}日 ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}
