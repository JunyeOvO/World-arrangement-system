from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SALVAGEABLE_FAILURE_REASONS = {
    "max_turns_no_diff",
    "worker_no_diff",
    "worker_ignored_early_output",
    "silent_max_turns_no_output",
}


@dataclass
class ReadOnlySalvageResult:
    summary: str
    source: str


class ReadOnlySalvagePolicy:
    """Salvages useful read-only worker output from failed attempts."""

    def salvage(self, task: dict[str, Any], worker_result: Any, failure: Any | None) -> ReadOnlySalvageResult | None:
        if _task_requires_diff(task) or getattr(worker_result, "changed_files", []):
            return None
        if not failure or failure.failure_reason not in SALVAGEABLE_FAILURE_REASONS:
            return None
        stdout_path = getattr(worker_result, "stdout_path", None)
        if stdout_path:
            summary = extract_worker_partial_text(Path(str(stdout_path)), task=task)
            if summary:
                setattr(worker_result, "partial_result", True)
                return ReadOnlySalvageResult(summary=_format_salvaged_summary(summary), source="worker_stream")
        raw_summary = str(getattr(worker_result, "summary", "") or "").strip()
        if (
            raw_summary
            and raw_summary.lower() not in {"claude code worker failed", "opencode worker failed"}
            and looks_like_meaningful_read_only_output(raw_summary, task=task)
        ):
            setattr(worker_result, "partial_result", True)
            return ReadOnlySalvageResult(summary=_format_salvaged_summary(raw_summary), source="worker_summary")
        return None


def extract_worker_success_text(path: Path) -> str | None:
    if not path.exists():
        return None
    result_text: str | None = None
    for event in _read_jsonl(path):
        if event.get("type") == "result" and event.get("subtype") == "success":
            raw = event.get("result")
            if isinstance(raw, str) and raw.strip():
                result_text = raw.strip()
        if event.get("type") != "result":
            for candidate in worker_text_candidates(event, include_thinking=False):
                if candidate.strip():
                    result_text = candidate.strip()
    return result_text


def extract_worker_partial_text(path: Path, task: dict[str, Any] | None = None) -> str | None:
    text = extract_worker_success_text(path)
    if text and looks_like_meaningful_read_only_output(text, task=task):
        return text
    candidates: list[str] = []
    chunks: list[str] = []
    if not path.exists():
        return None
    for event in _read_jsonl(path):
        candidates.extend(worker_text_candidates(event, include_thinking=True))
        delta = event.get("delta")
        if event.get("type") != "content_block_delta" and isinstance(delta, dict):
            raw_delta = delta.get("text") or delta.get("content")
            if isinstance(raw_delta, str) and raw_delta.strip():
                chunks.append(raw_delta)
        if event.get("type") == "content_block_delta" and isinstance(delta, dict):
            raw_delta = delta.get("text")
            if isinstance(raw_delta, str) and raw_delta.strip():
                chunks.append(raw_delta)
    if chunks:
        candidates.append("".join(chunks).strip())
    meaningful = [
        candidate.strip()
        for candidate in candidates
        if looks_like_meaningful_read_only_output(candidate, task=task)
    ]
    if meaningful:
        return _trim_salvage_text(meaningful[-1])
    return None


def worker_text_candidates(event: dict[str, Any], *, include_thinking: bool = False) -> list[str]:
    candidates: list[str] = []
    raw_result = event.get("result")
    if isinstance(raw_result, str) and raw_result.strip():
        candidates.append(raw_result)
    raw_text = event.get("text")
    if isinstance(raw_text, str) and raw_text.strip():
        candidates.append(raw_text)
    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, list):
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                item_text = item.get("text")
                if item_type == "text" and isinstance(item_text, str):
                    text_parts.append(item_text)
                if include_thinking and item_type == "thinking" and isinstance(item.get("thinking"), str):
                    thinking_parts.append(item["thinking"])
            text = "\n".join(text_parts).strip()
            if text:
                candidates.append(text)
            thinking = "\n".join(thinking_parts).strip()
            if thinking:
                candidates.append(thinking)
        elif isinstance(content, str) and content.strip():
            candidates.append(content)
    part = event.get("part")
    if isinstance(part, dict):
        raw_part = part.get("text")
        if isinstance(raw_part, str) and raw_part.strip():
            candidates.append(raw_part)
    return candidates


def looks_like_meaningful_read_only_output(text: str, task: dict[str, Any] | None = None) -> bool:
    stripped = text.strip()
    lowered = stripped.lower()
    completion_markers = ("completed", "finished", "done", "完成", "已完成")
    if len(stripped) >= 20 and any(marker in lowered for marker in completion_markers):
        return True
    if len(stripped) < 120:
        return False
    exploratory_markers = (
        "i'll inspect",
        "i will inspect",
        "let me inspect",
        "let me check",
        "i need to inspect",
        "i'll read",
        "i will read",
        "先检查",
        "先看",
        "我先",
    )
    if any(marker in lowered for marker in exploratory_markers) and len(stripped) < 500:
        return False
    result_markers = (
        "summary",
        "overview",
        "risk",
        "recommend",
        "next",
        "changed_files",
        "验收",
        "结论",
        "风险",
        "建议",
        "下一步",
        "候选",
    )
    profile = str((task or {}).get("read_budget_profile") or "").lower()
    if profile == "code_contract_audit":
        result_markers += (
            "contract",
            "producer",
            "consumer",
            "mismatch",
            "workarea",
            "work area",
            "normalization",
            "契约",
            "生产",
            "消费",
            "不匹配",
        )
    return any(marker in lowered for marker in result_markers)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            rows.append(event)
    return rows


def _format_salvaged_summary(summary: str) -> str:
    return f"Partial read-only result salvaged after worker budget limit.\n\n{summary}"


def _trim_salvage_text(text: str, limit: int = 6000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[-limit:].strip()


def _task_requires_diff(task: dict[str, Any]) -> bool:
    if task.get("expected_diff") is not None:
        return bool(task.get("expected_diff"))
    if str(task.get("task_mode") or "").lower() in {"read_only", "audit"}:
        return False
    if task.get("allow_empty_diff") is True:
        return False
    goal = str(task.get("user_goal", "")).lower()
    explicit_no_write_markers = (
        "read-only",
        "readonly",
        "no changes",
        "do not modify",
        "do not edit",
        "do not write",
        "do not change files",
        "without modifying",
        "只读",
        "不修改",
        "不要修改",
        "不改",
        "不要改",
        "不写入",
        "不自动改文件",
        "只做只读分析",
    )
    return not any(marker in goal for marker in explicit_no_write_markers)
