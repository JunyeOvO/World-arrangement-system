export function RouteDecisionCard({ route }: { route?: Record<string, unknown> }) {
  return (
    <section className="panel">
      <h2>Route</h2>
      <pre>{JSON.stringify(route ?? {}, null, 2)}</pre>
    </section>
  );
}

