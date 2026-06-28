import { TimelineEvent } from "../api/client";

export function TaskTimeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id}>
          <span>{event.at}</span>
          <strong>{event.event_type}</strong>
          <small>{[event.from_state, event.to_state].filter(Boolean).join(" -> ")}</small>
        </li>
      ))}
    </ol>
  );
}

