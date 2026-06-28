import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, BarChart3, ClipboardList, LayoutDashboard } from "lucide-react";
import { useConsoleSnapshot } from "./state/useConsole";
import { Overview } from "./pages/Overview";
import { TaskDetail } from "./pages/TaskDetail";
import { Metrics } from "./pages/Metrics";
import { Audit } from "./pages/Audit";
import "./styles.css";

type Page = "overview" | "task" | "metrics" | "audit";

function App() {
  const { snapshot, error } = useConsoleSnapshot();
  const [page, setPage] = useState<Page>("overview");
  const [taskId, setTaskId] = useState<string | null>(null);

  const selectTask = (id: string) => {
    setTaskId(id);
    setPage("task");
  };

  return (
    <main>
      <aside>
        <div className="brand"><Activity size={22} /> World</div>
        <button className={page === "overview" ? "active" : ""} onClick={() => setPage("overview")}><LayoutDashboard size={17} /> Overview</button>
        <button className={page === "metrics" ? "active" : ""} onClick={() => setPage("metrics")}><BarChart3 size={17} /> Metrics</button>
        <button className={page === "audit" ? "active" : ""} onClick={() => setPage("audit")}><ClipboardList size={17} /> Audit</button>
      </aside>
      <section className="workspace">
        {error && <div className="banner">{error}</div>}
        {!snapshot && <div className="panel">Loading console...</div>}
        {snapshot && page === "overview" && <Overview snapshot={snapshot} onSelectTask={selectTask} />}
        {snapshot && page === "metrics" && <Metrics snapshot={snapshot} />}
        {page === "audit" && <Audit />}
        {page === "task" && taskId && <TaskDetail taskId={taskId} />}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);

