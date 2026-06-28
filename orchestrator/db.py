from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, is_dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  project_id TEXT,
  repo_path TEXT,
  user_goal TEXT,
  status TEXT,
  created_at TEXT,
  updated_at TEXT,
  route_worker TEXT,
  route_model TEXT,
  route_variant TEXT,
  pr_url TEXT,
  run_dir TEXT
);

CREATE TABLE IF NOT EXISTS task_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  at TEXT,
  event_type TEXT,
  from_state TEXT,
  to_state TEXT,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS task_attempts (
  task_id TEXT,
  stage TEXT,
  attempt_no INTEGER,
  worker TEXT,
  model TEXT,
  variant TEXT,
  started_at TEXT,
  ended_at TEXT,
  exit_code INTEGER,
  error_code TEXT
);

CREATE TABLE IF NOT EXISTS task_metrics (
  task_id TEXT,
  attempt_no INTEGER,
  worker TEXT,
  model TEXT,
  status TEXT,
  failure_reason TEXT,
  total_cost_usd REAL,
  duration_ms INTEGER,
  duration_api_ms INTEGER,
  num_turns INTEGER,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cache_read_input_tokens INTEGER,
  changed_files_count INTEGER,
  build_passed BOOLEAN,
  review_approved BOOLEAN,
  created_at TEXT,
  PRIMARY KEY(task_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS codex_usage_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  phase TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  actual_codex_used BOOLEAN NOT NULL,
  estimation_method TEXT NOT NULL,
  created_at TEXT NOT NULL,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS approval_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  task_type TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  approval_mode TEXT NOT NULL,
  worker TEXT,
  model TEXT,
  variant TEXT,
  planned_files_count INTEGER,
  actual_files_count INTEGER,
  changed_paths_json TEXT,
  tests_passed BOOLEAN,
  codex_review_approved BOOLEAN,
  pr_created BOOLEAN,
  pr_merged BOOLEAN,
  rollback BOOLEAN,
  incident BOOLEAN,
  user_decision TEXT,
  user_feedback TEXT
);

CREATE TABLE IF NOT EXISTS learned_patterns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  task_type TEXT NOT NULL,
  path_pattern TEXT NOT NULL,
  worker TEXT,
  model TEXT,
  variant TEXT,
  approvals_count INTEGER DEFAULT 0,
  success_count INTEGER DEFAULT 0,
  failure_count INTEGER DEFAULT 0,
  rollback_count INTEGER DEFAULT 0,
  trust_score REAL DEFAULT 0,
  confidence REAL DEFAULT 0,
  suggested_mode TEXT,
  active BOOLEAN DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  expires_at TEXT
);

CREATE TABLE IF NOT EXISTS approval_policy_overrides (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  rule_name TEXT NOT NULL,
  matcher_json TEXT NOT NULL,
  approval_mode TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS policy_suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  suggestion_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS worker_heartbeats (
  worker_id TEXT,
  task_id TEXT,
  attempt_id TEXT,
  ts TEXT,
  status TEXT,
  phase TEXT,
  pid INTEGER,
  model_key TEXT,
  cost_usd REAL,
  turns INTEGER,
  last_event_id TEXT,
  PRIMARY KEY(worker_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS system_alerts (
  alert_id TEXT PRIMARY KEY,
  ts TEXT,
  severity TEXT,
  source TEXT,
  task_id TEXT,
  rule_id TEXT,
  title TEXT,
  message TEXT,
  status TEXT,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS console_task_dismissals (
  task_id TEXT PRIMARY KEY,
  dismissed_at TEXT NOT NULL,
  dismissed_by TEXT NOT NULL,
  reason TEXT
);
"""


class TaskDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        retries = 5
        delay = 0.05
        last_error: Exception | None = None
        for _ in range(retries):
            try:
                con = sqlite3.connect(self.path, timeout=3)
                con.row_factory = sqlite3.Row
                yield con
                con.commit()
                con.close()
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if "locked" not in str(exc).lower():
                    raise
                time.sleep(delay)
                delay *= 2
        if last_error:
            raise last_error

    def init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    def create_task(self, row: dict[str, Any]) -> None:
        self.init()
        columns = [
            "task_id",
            "project_id",
            "repo_path",
            "user_goal",
            "status",
            "created_at",
            "updated_at",
            "route_worker",
            "route_model",
            "route_variant",
            "pr_url",
            "run_dir",
        ]
        values = [row.get(c) for c in columns]
        with self.connect() as con:
            con.execute(
                f"INSERT INTO tasks ({','.join(columns)}) VALUES ({','.join(['?'] * len(columns))})",
                values,
            )

    def update_task(self, task_id: str, **updates: Any) -> None:
        if not updates:
            return
        with self.connect() as con:
            assignments = ", ".join(f"{key}=?" for key in updates)
            con.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id=?",
                [*updates.values(), task_id],
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self.init()
        with self.connect() as con:
            row = con.execute("SELECT * FROM tasks WHERE task_id=?", [task_id]).fetchone()
        return dict(row) if row else None

    def append_event(
        self,
        task_id: str,
        event_type: str,
        from_state: str | None,
        to_state: str | None,
        payload: dict[str, Any] | None = None,
        at: str | None = None,
    ) -> None:
        at = at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO task_events(task_id, at, event_type, from_state, to_state, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [task_id, at, event_type, from_state, to_state, json.dumps(_json_safe(payload or {}))],
            )

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY id ASC", [task_id]
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_task_metrics(self, row: dict[str, Any]) -> None:
        self.init()
        cols = [
            "task_id",
            "attempt_no",
            "worker",
            "model",
            "status",
            "failure_reason",
            "total_cost_usd",
            "duration_ms",
            "duration_api_ms",
            "num_turns",
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "changed_files_count",
            "build_passed",
            "review_approved",
            "created_at",
        ]
        values = [row.get(c) for c in cols]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols[2:])
        with self.connect() as con:
            con.execute(
                f"""
                INSERT INTO task_metrics ({','.join(cols)})
                VALUES ({','.join(['?'] * len(cols))})
                ON CONFLICT(task_id, attempt_no) DO UPDATE SET {assignments}
                """,
                values,
            )

    def list_task_metrics(self, task_id: str) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM task_metrics WHERE task_id=? ORDER BY attempt_no ASC",
                [task_id],
            ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_task_metrics(self, limit: int = 500) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 2000))
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT * FROM task_metrics
                ORDER BY created_at DESC, task_id DESC, attempt_no DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def record_codex_usage_event(self, row: dict[str, Any]) -> None:
        self.init()
        cols = [
            "task_id",
            "phase",
            "model",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "actual_codex_used",
            "estimation_method",
            "created_at",
            "metadata_json",
        ]
        values = [
            row.get("task_id"),
            row.get("phase"),
            row.get("model", "codex"),
            int(row.get("input_tokens") or 0),
            int(row.get("output_tokens") or 0),
            int(row.get("total_tokens") or 0),
            bool(row.get("actual_codex_used")),
            row.get("estimation_method"),
            row.get("created_at"),
            json.dumps(_json_safe(row.get("metadata") or row.get("metadata_json") or {}), ensure_ascii=False),
        ]
        with self.connect() as con:
            con.execute(
                f"INSERT INTO codex_usage_events ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                values,
            )

    def list_codex_usage_events(
        self,
        task_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 2000))
        params: list[Any] = []
        where = ""
        if task_id:
            where = "WHERE task_id=?"
            params.append(task_id)
        with self.connect() as con:
            rows = con.execute(
                f"""
                SELECT * FROM codex_usage_events
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw_metadata = item.pop("metadata_json", None)
            try:
                item["metadata"] = json.loads(raw_metadata or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            result.append(item)
        return result

    def model_metrics_summary(self) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT
                  model,
                  worker,
                  COUNT(*) AS attempts,
                  AVG(total_cost_usd) AS avg_cost_usd,
                  AVG(CASE WHEN status IN ('success', 'COMPLETED_WITH_PATCH', 'PR_CREATED', 'DONE') THEN 1.0 ELSE 0.0 END) AS success_rate
                FROM task_metrics
                GROUP BY model, worker
                ORDER BY attempts DESC, model ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Approval Graph methods ──

    def record_approval_event(self, row: dict[str, Any]) -> None:
        """Insert an approval event row."""
        self.init()
        cols = [
            "task_id", "project_id", "created_at", "task_type", "risk_level",
            "approval_mode", "worker", "model", "variant",
            "planned_files_count", "actual_files_count", "changed_paths_json",
            "tests_passed", "codex_review_approved", "pr_created", "pr_merged",
            "rollback", "incident", "user_decision", "user_feedback",
        ]
        values = [row.get(c) for c in cols]
        with self.connect() as con:
            con.execute(
                f"INSERT INTO approval_events ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                values,
            )

    def get_approval_history(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM approval_events WHERE project_id=? ORDER BY id DESC LIMIT ?",
                [project_id, limit],
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_learned_pattern(self, row: dict[str, Any]) -> None:
        """Insert or update a learned pattern by project+task_type+path_pattern uniqueness."""
        self.init()
        with self.connect() as con:
            existing = con.execute(
                "SELECT id, approvals_count, success_count, failure_count, rollback_count, trust_score FROM learned_patterns WHERE project_id=? AND task_type=? AND path_pattern=?",
                [row["project_id"], row["task_type"], row["path_pattern"]],
            ).fetchone()
            if existing:
                e = dict(existing)
                new_approvals = e["approvals_count"] + row.get("approvals_count", 0)
                new_success = e["success_count"] + row.get("success_count", 0)
                new_failure = e["failure_count"] + row.get("failure_count", 0)
                new_rollback = e["rollback_count"] + row.get("rollback_count", 0)
                total = new_success + new_failure + new_rollback
                new_trust = (new_success * 1.0 - new_failure * 0.5 - new_rollback * 2.0) / max(total, 1)
                new_trust = max(0.0, min(1.0, new_trust + 0.5))
                con.execute(
                    """UPDATE learned_patterns SET
                       approvals_count=?, success_count=?, failure_count=?,
                       rollback_count=?, trust_score=?, updated_at=?
                       WHERE id=?""",
                    [new_approvals, new_success, new_failure, new_rollback, new_trust, row.get("updated_at", ""), e["id"]],
                )
            else:
                cols = [
                    "project_id", "task_type", "path_pattern", "worker", "model", "variant",
                    "approvals_count", "success_count", "failure_count", "rollback_count",
                    "trust_score", "confidence", "suggested_mode", "active",
                    "created_at", "updated_at", "expires_at",
                ]
                values = [row.get(c) for c in cols]
                con.execute(
                    f"INSERT INTO learned_patterns ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                    values,
                )

    def get_learned_patterns(self, project_id: str, active_only: bool = True) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            where = "project_id=? AND active=1" if active_only else "project_id=?"
            rows = con.execute(
                f"SELECT * FROM learned_patterns WHERE {where} ORDER BY trust_score DESC",
                [project_id],
            ).fetchall()
        return [dict(r) for r in rows]

    def revoke_learned_pattern(self, pattern_id: int) -> None:
        self.init()
        with self.connect() as con:
            con.execute("UPDATE learned_patterns SET active=0 WHERE id=?", [pattern_id])

    def add_policy_override(self, row: dict[str, Any]) -> None:
        self.init()
        cols = ["project_id", "rule_name", "matcher_json", "approval_mode", "created_by", "created_at", "expires_at", "active"]
        values = [row.get(c) for c in cols]
        with self.connect() as con:
            con.execute(
                f"INSERT INTO approval_policy_overrides ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                values,
            )

    def get_policy_overrides(self, project_id: str) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM approval_policy_overrides WHERE project_id=? AND active=1", [project_id]
            ).fetchall()
        return [dict(r) for r in rows]

    def add_policy_suggestion(self, row: dict[str, Any]) -> None:
        self.init()
        cols = ["project_id", "suggestion_json", "status", "created_at", "decided_at"]
        values = [row.get(c) for c in cols]
        with self.connect() as con:
            con.execute(
                f"INSERT INTO policy_suggestions ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                values,
            )

    def get_policy_suggestions(self, project_id: str, status: str | None = None) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as con:
            if status:
                rows = con.execute(
                    "SELECT * FROM policy_suggestions WHERE project_id=? AND status=? ORDER BY id DESC",
                    [project_id, status],
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM policy_suggestions WHERE project_id=? ORDER BY id DESC", [project_id]
                ).fetchall()
        return [dict(r) for r in rows]

    def update_policy_suggestion(self, suggestion_id: int, status: str, decided_at: str | None = None) -> None:
        self.init()
        with self.connect() as con:
            con.execute(
                "UPDATE policy_suggestions SET status=?, decided_at=? WHERE id=?",
                [status, decided_at, suggestion_id],
            )

    # -- Console methods --

    def list_tasks(
        self,
        status: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.init()
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 500))
        with self.connect() as con:
            rows = con.execute(
                f"SELECT * FROM tasks {where} ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def list_recent_events(self, limit: int = 100, after_id: int | None = None) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 1000))
        with self.connect() as con:
            if after_id is None:
                rows = con.execute(
                    "SELECT * FROM task_events ORDER BY id DESC LIMIT ?",
                    [limit],
                ).fetchall()
                return [dict(row) for row in reversed(rows)]
            rows = con.execute(
                "SELECT * FROM task_events WHERE id>? ORDER BY id ASC LIMIT ?",
                [after_id, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def list_audit_events(
        self,
        task_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.init()
        clauses: list[str] = []
        params: list[Any] = []
        if task_id:
            clauses.append("task_id=?")
            params.append(task_id)
        if action:
            clauses.append("event_type=?")
            params.append(action)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit = max(1, min(int(limit), 500))
        with self.connect() as con:
            rows = con.execute(
                f"SELECT * FROM task_events {where} ORDER BY id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_worker_heartbeat(self, row: dict[str, Any]) -> None:
        self.init()
        cols = [
            "worker_id",
            "task_id",
            "attempt_id",
            "ts",
            "status",
            "phase",
            "pid",
            "model_key",
            "cost_usd",
            "turns",
            "last_event_id",
        ]
        values = [row.get(c) for c in cols]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols[3:])
        with self.connect() as con:
            con.execute(
                f"""
                INSERT INTO worker_heartbeats ({','.join(cols)})
                VALUES ({','.join(['?'] * len(cols))})
                ON CONFLICT(worker_id, attempt_id) DO UPDATE SET {assignments}
                """,
                values,
            )

    def list_worker_heartbeats(self, limit: int = 100) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 500))
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM worker_heartbeats ORDER BY ts DESC LIMIT ?",
                [limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_system_alert(self, row: dict[str, Any]) -> None:
        self.init()
        cols = [
            "alert_id",
            "ts",
            "severity",
            "source",
            "task_id",
            "rule_id",
            "title",
            "message",
            "status",
            "resolved_at",
        ]
        values = [row.get(c) for c in cols]
        assignments = ", ".join(f"{c}=excluded.{c}" for c in cols[1:])
        with self.connect() as con:
            con.execute(
                f"""
                INSERT INTO system_alerts ({','.join(cols)})
                VALUES ({','.join(['?'] * len(cols))})
                ON CONFLICT(alert_id) DO UPDATE SET {assignments}
                """,
                values,
            )

    def list_system_alerts(self, status: str | None = "open", limit: int = 100) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 500))
        with self.connect() as con:
            if status:
                rows = con.execute(
                    "SELECT * FROM system_alerts WHERE status=? ORDER BY ts DESC LIMIT ?",
                    [status, limit],
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM system_alerts ORDER BY ts DESC LIMIT ?",
                    [limit],
                ).fetchall()
        return [dict(row) for row in rows]

    def resolve_system_alert(self, alert_id: str, resolved_at: str) -> bool:
        self.init()
        with self.connect() as con:
            cur = con.execute(
                "UPDATE system_alerts SET status='resolved', resolved_at=? WHERE alert_id=?",
                [resolved_at, alert_id],
            )
        return cur.rowcount > 0

    def dismiss_console_task(
        self,
        task_id: str,
        dismissed_at: str,
        dismissed_by: str = "console",
        reason: str = "",
    ) -> None:
        self.init()
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO console_task_dismissals(task_id, dismissed_at, dismissed_by, reason)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                  dismissed_at=excluded.dismissed_at,
                  dismissed_by=excluded.dismissed_by,
                  reason=excluded.reason
                """,
                [task_id, dismissed_at, dismissed_by, reason],
            )

    def list_console_dismissed_task_ids(self) -> set[str]:
        self.init()
        with self.connect() as con:
            rows = con.execute("SELECT task_id FROM console_task_dismissals").fetchall()
        return {str(row["task_id"]) for row in rows}


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
