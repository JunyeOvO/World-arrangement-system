import { useEffect, useState } from "react";
import { api, TimelineEvent } from "../api/client";

export function Audit() {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  useEffect(() => {
    api.audit().then((payload) => setEvents(payload.events));
  }, []);
  return (
    <section className="panel">
      <h2>Audit</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Task</th><th>Action</th><th>Transition</th></tr></thead>
          <tbody>
            {events.map((event) => (
              <tr key={event.id}>
                <td>{event.at}</td>
                <td>{event.task_id}</td>
                <td>{event.event_type}</td>
                <td>{[event.from_state, event.to_state].filter(Boolean).join(" -> ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

