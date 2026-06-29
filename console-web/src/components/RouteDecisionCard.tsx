type RouteRecord = Record<string, unknown>;

export function RouteDecisionCard({ route }: { route?: RouteRecord }) {
  const selected = compact([
    text(route?.selected_worker),
    text(route?.selected_model),
    text(route?.variant),
  ]).join(" / ") || "pending";
  const agent = text(route?.agent_llm);
  const taskShape = text(route?.task_shape);
  const confidence = number(route?.confidence);
  const budgetEstimate = number(route?.budget_estimate_usd);
  const budgetCap = number(route?.budget_cap_usd);
  const reason = text(route?.reason);
  const matchedRules = stringList(route?.matched_rules);
  const fallback = fallbackLabels(route?.retry_chain, route?.fallback_models);
  const rejected = rejectedCandidates(route?.rejected_candidates);
  const history = historyDecision(route?.history_basis);

  return (
    <section className="panel route-panel">
      <div className="panel-head">
        <h2>Route</h2>
        {confidence !== null && <span className="process-count">{Math.round(confidence * 100)}%</span>}
      </div>

      <div className="route-summary">
        <div>
          <small>Selected</small>
          <strong>{selected}</strong>
          {agent && <span>{agent}</span>}
        </div>
        <div>
          <small>Task shape</small>
          <strong>{taskShape || "unknown"}</strong>
          <span>{budgetText(budgetEstimate, budgetCap)}</span>
        </div>
      </div>

      {reason && (
        <div className="route-reason">
          <small>Reason</small>
          <p>{reason}</p>
        </div>
      )}

      {history && (
        <div className="route-history">
          <small>History decision</small>
          <strong>{history.selected}</strong>
          <span>{history.scores}</span>
        </div>
      )}

      <div className="route-columns">
        <RouteList title="Matched rules" items={matchedRules} empty="No matched rules recorded" />
        <RouteList title="Fallback chain" items={fallback} empty="No fallback chain recorded" />
      </div>

      {rejected.length > 0 && (
        <div className="route-rejected">
          <small>Rejected candidates</small>
          {rejected.slice(0, 4).map((candidate) => (
            <div className="route-rejected-row" key={candidate.key}>
              <span>{candidate.label}</span>
              <code>{candidate.score}</code>
            </div>
          ))}
        </div>
      )}

      <details className="route-raw">
        <summary>Raw route JSON</summary>
        <pre>{JSON.stringify(route ?? {}, null, 2)}</pre>
      </details>
    </section>
  );
}

function RouteList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="route-list">
      <small>{title}</small>
      {items.length ? (
        <ul>
          {items.slice(0, 6).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
        </ul>
      ) : (
        <span>{empty}</span>
      )}
    </div>
  );
}

function compact(values: string[]) {
  return values.filter(Boolean);
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function number(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item)).filter(Boolean)
    : [];
}

function budgetText(estimate: number | null, cap: number | null): string {
  if (estimate === null && cap === null) return "budget not recorded";
  if (estimate !== null && cap !== null) return `$${estimate.toFixed(4)} est / $${cap.toFixed(4)} cap`;
  if (estimate !== null) return `$${estimate.toFixed(4)} estimated`;
  return `$${cap?.toFixed(4)} cap`;
}

function fallbackLabels(retryChain: unknown, fallbackModels: unknown): string[] {
  if (Array.isArray(retryChain)) {
    return retryChain.map((item, index) => {
      if (!isRecord(item)) return "";
      return compact([
        `${index + 1}.`,
        text(item.worker),
        text(item.model),
        text(item.variant),
      ]).join(" ");
    }).filter(Boolean);
  }
  return stringList(fallbackModels);
}

function rejectedCandidates(value: unknown): Array<{ key: string; label: string; score: string }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (!isRecord(item)) return [];
    const label = compact([text(item.worker), text(item.model)]).join(" / ") || `candidate ${index + 1}`;
    const rawScore = number(item.score);
    return [{
      key: `${label}-${index}`,
      label,
      score: rawScore === null ? "n/a" : rawScore.toFixed(1),
    }];
  });
}

function historyDecision(value: unknown): { selected: string; scores: string } | null {
  if (!isRecord(value) || !isRecord(value._decision)) return null;
  const selected = text(value._decision.selected) || "unknown";
  const scores = isRecord(value._decision.scores)
    ? Object.entries(value._decision.scores)
      .map(([key, score]) => `${key}: ${typeof score === "number" ? score.toFixed(3) : String(score)}`)
      .join(" | ")
    : "scores unavailable";
  return { selected, scores };
}

function isRecord(value: unknown): value is RouteRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
