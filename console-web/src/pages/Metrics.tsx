import { ConsoleSnapshot } from "../api/client";

export function Metrics({ snapshot }: { snapshot: ConsoleSnapshot }) {
  return (
    <div className="detail-grid">
      <section className="panel">
        <h2>Summary</h2>
        <dl>
          <dt>Attempts</dt><dd>{snapshot.metrics.attempts}</dd>
          <dt>Total cost</dt><dd>${snapshot.metrics.total_cost_usd.toFixed(4)}</dd>
          <dt>P95 duration</dt><dd>{snapshot.metrics.p95_duration_ms} ms</dd>
        </dl>
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

