import { useEffect, useState } from "react";
import { RotateCcw, XCircle } from "lucide-react";
import { api, TaskDetail as TaskDetailData } from "../api/client";
import { RouteDecisionCard } from "../components/RouteDecisionCard";
import { TaskTimeline } from "../components/TaskTimeline";

export function TaskDetail({ taskId }: { taskId: string }) {
  const [detail, setDetail] = useState<TaskDetailData | null>(null);
  const [output, setOutput] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [outputError, setOutputError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setOutput("");
    setOutputError(null);
    api.taskDetail(taskId)
      .then((payload) => {
        setDetail(payload);
        const hasFinal = payload.artifacts.some((artifact) => artifact.path === "final.md");
        if (!hasFinal) {
          setOutputError("No final output recorded yet.");
          return;
        }
        api.taskArtifact(taskId, "final.md")
          .then(setOutput)
          .catch((err) => setOutputError(err.message));
      })
      .catch((err) => setError(err.message));
  }, [taskId]);

  if (error) return <section className="panel danger">{error}</section>;
  if (!detail) return <section className="panel">Loading task...</section>;

  const visibleStatus = detail.task.display_status || detail.task.status;

  return (
    <div className="detail-grid">
      <section className="panel">
        <div className="panel-head">
          <h2>{detail.task.task_id}</h2>
          <div className="actions">
            <button title="Cancel task" onClick={() => void api.cancelTask(detail.task.task_id)}><XCircle size={16} /></button>
            <button title="Retry task" onClick={() => void api.retryTask(detail.task.task_id)}><RotateCcw size={16} /></button>
          </div>
        </div>
        <p>{detail.task.user_goal}</p>
        <span className={`status ${visibleStatus.toLowerCase()}`}>{visibleStatus}</span>
        {detail.task.status_note && <small>{detail.task.status_note}</small>}
        {detail.task.display_status && detail.task.display_status !== detail.task.status && (
          <small>Raw state: {detail.task.status}</small>
        )}
      </section>
      <RouteDecisionCard route={detail.route_decision} />
      <section className="panel timeline-panel">
        <h2>Timeline</h2>
        <TaskTimeline events={detail.timeline} />
      </section>
      <section className="panel output-panel">
        <h2>Output</h2>
        {output ? <MarkdownPreview source={output} /> : <p>{outputError || "Loading output..."}</p>}
      </section>
      <section className="panel">
        <h2>Verify</h2>
        <pre>{JSON.stringify(detail.verify ?? {}, null, 2)}</pre>
      </section>
      <section className="panel">
        <h2>Review</h2>
        <pre>{JSON.stringify(detail.review ?? {}, null, 2)}</pre>
      </section>
      <section className="panel artifacts-panel">
        <h2>Artifacts</h2>
        <div className="artifact-list">
          {detail.artifacts.map((artifact) => <a href={artifact.url} key={artifact.path}>{artifact.path}</a>)}
        </div>
      </section>
    </div>
  );
}

function MarkdownPreview({ source }: { source: string }) {
  const blocks = parseMarkdownBlocks(source);
  return (
    <div className="markdown-preview">
      {blocks.map((block, index) => {
        if (block.type === "h1") return <h1 key={index}>{block.text}</h1>;
        if (block.type === "h2") return <h2 key={index}>{block.text}</h2>;
        if (block.type === "h3") return <h3 key={index}>{block.text}</h3>;
        if (block.type === "list") {
          return (
            <ul key={index}>
              {block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInlineMarkdown(item)}</li>)}
            </ul>
          );
        }
        if (block.type === "code") return <pre key={index}><code>{block.text}</code></pre>;
        return <p key={index}>{renderInlineMarkdown(block.text)}</p>;
      })}
    </div>
  );
}

type MarkdownBlock =
  | { type: "h1" | "h2" | "h3" | "paragraph" | "code"; text: string }
  | { type: "list"; items: string[] };

function parseMarkdownBlocks(source: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];
  let list: string[] = [];
  let code: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      blocks.push({ type: "list", items: list });
      list = [];
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (inCode) {
        blocks.push({ type: "code", text: code.join("\n") });
        code = [];
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    if (trimmed.startsWith("### ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "h3", text: trimmed.slice(4) });
      continue;
    }
    if (trimmed.startsWith("## ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "h2", text: trimmed.slice(3) });
      continue;
    }
    if (trimmed.startsWith("# ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "h1", text: trimmed.slice(2) });
      continue;
    }
    if (trimmed.startsWith("- ")) {
      flushParagraph();
      list.push(trimmed.slice(2));
      continue;
    }
    paragraph.push(trimmed);
  }
  if (inCode) blocks.push({ type: "code", text: code.join("\n") });
  flushParagraph();
  flushList();
  return blocks;
}

function renderInlineMarkdown(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}
