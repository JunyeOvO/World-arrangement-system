import { CSSProperties, useEffect, useMemo, useState } from "react";
import { ChartColumn } from "lucide-react";
import { api, ConsoleSnapshot, MetricsUsage } from "../api/client";

export function Metrics({ snapshot }: { snapshot: ConsoleSnapshot }) {
  const [usage, setUsage] = useState<MetricsUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.metricsUsage().then(setUsage).catch((err) => setError(err.message));
  }, []);

  return (
    <div className="metrics-page">
      <section className="panel">
        <h2>Summary</h2>
        <dl>
          <dt>Attempts</dt><dd>{snapshot.metrics.attempts}</dd>
          <dt>Total cost</dt><dd>${snapshot.metrics.total_cost_usd.toFixed(4)}</dd>
          <dt>P95 duration</dt><dd>{snapshot.metrics.p95_duration_ms} ms</dd>
        </dl>
      </section>
      <section className="panel metrics-wide">
        <h2>Cost by Model</h2>
        {error && <div className="banner">{error}</div>}
        <CostChart usage={usage} />
      </section>
      <section className="panel metrics-wide">
        <h2>Model Calls</h2>
        <UsageTable usage={usage} />
      </section>
      <section className="panel">
        <h2>Models</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Worker</th><th>Model</th><th>Attempts</th><th>Success</th><th>Avg Cost</th></tr></thead>
            <tbody>
              {snapshot.models.map((model) => (
                <tr key={`${model.worker}-${model.model}`}>
                  <td>{model.worker}</td>
                  <td>{model.model}</td>
                  <td>{model.attempts}</td>
                  <td>{((model.success_rate ?? 0) * 100).toFixed(1)}%</td>
                  <td>${(model.avg_cost_usd ?? 0).toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
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
