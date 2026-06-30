from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract_worker_success_text(path: Path) -> str | None:
    if not path.exists():
        return None
    result_text: str | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result" and event.get("subtype") == "success":
            raw = event.get("result")
            if isinstance(raw, str) and raw.strip():
                result_text = raw.strip()
        message = event.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                text = "\n".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
                ).strip()
                if text:
                    result_text = text
        part = event.get("part")
        if event.get("type") == "text" and isinstance(part, dict):
            raw_text = part.get("text")
            if isinstance(raw_text, str) and raw_text.strip():
                result_text = raw_text.strip()
    return result_text


def extract_worker_partial_text(path: Path) -> str | None:
    text = extract_worker_success_text(path)
    if text and looks_like_meaningful_read_only_output(text):
        return text
    chunks: list[str] = []
    candidates: list[str] = []
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        for candidate in worker_text_candidates(event):
            candidates.append(candidate)
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
    meaningful = [candidate.strip() for candidate in candidates if looks_like_meaningful_read_only_output(candidate)]
    if meaningful:
        return meaningful[-1]
    return None


def worker_text_candidates(event: dict[str, Any]) -> list[str]:
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
            text = "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
            ).strip()
            if text:
                candidates.append(text)
        elif isinstance(content, str) and content.strip():
            candidates.append(content)
    part = event.get("part")
    if isinstance(part, dict):
        raw_part = part.get("text")
        if isinstance(raw_part, str) and raw_part.strip():
            candidates.append(raw_part)
    return candidates


def looks_like_meaningful_read_only_output(text: str) -> bool:
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
    return any(marker in lowered for marker in result_markers)


def read_only_result_can_finish(task: dict[str, Any], worker_result: Any) -> bool:
    return (
        not task_requires_diff(task)
        and getattr(worker_result, "status", "") == "success"
        and not getattr(worker_result, "changed_files", [])
    )


def read_only_failure_summary(
    task: dict[str, Any],
    worker_result: Any,
    failure: Any | None,
) -> str | None:
    if task_requires_diff(task) or getattr(worker_result, "changed_files", []):
        return None
    if not failure or failure.failure_reason not in {"max_turns_no_diff", "worker_no_diff"}:
        return None
    stdout_path = getattr(worker_result, "stdout_path", None)
    summary = extract_worker_partial_text(Path(str(stdout_path))) if stdout_path else None
    if summary:
        setattr(worker_result, "partial_result", True)
        return f"Partial read-only result salvaged after worker budget limit.\n\n{summary}"
    raw_summary = str(getattr(worker_result, "summary", "") or "").strip()
    if (
        raw_summary
        and raw_summary.lower() not in {"claude code worker failed", "opencode worker failed"}
        and looks_like_meaningful_read_only_output(raw_summary)
    ):
        setattr(worker_result, "partial_result", True)
        return f"Partial read-only result salvaged after worker budget limit.\n\n{raw_summary}"
    return None


def read_only_review(task: dict[str, Any], reason: str = "read_only_no_diff") -> dict[str, Any]:
    return {
        "approved": True,
        "review_mode": "skipped_read_only",
        "degraded": False,
        "degradation_reason": None,
        "available": True,
        "risk_level": task.get("risk_level", "medium"),
        "blocking_issues": [],
        "non_blocking_issues": [],
        "required_changes": [],
        "final_recommendation": "read-only task completed with artifacts; no patch or PR is required",
        "can_create_pr": False,
        "reason": reason,
    }


def task_requires_diff(task: dict[str, Any]) -> bool:
    goal = str(task.get("user_goal", "")).lower()
    task_type = str(task.get("task_type", "")).lower()
    if task.get("expected_diff") is not None:
        return bool(task.get("expected_diff"))
    if str(task.get("task_mode") or "").lower() in {"read_only", "audit"}:
        return False
    if task.get("allow_empty_diff") is True:
        return False
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
    if any(marker in goal for marker in explicit_no_write_markers):
        return False
    read_only_markers = (
        "analyze",
        "analysis",
        "evaluate",
        "assessment",
        "review",
        "inspect",
        "read-only",
        "no changes",
        "do not modify",
        "do not edit",
        "只读",
        "分析",
        "评价",
        "评估",
        "审查",
        "检查",
        "不修改",
        "不要修改",
        "不改",
        "不要改",
        "不写入",
    )
    strong_edit_markers = (
        "fix",
        "implement",
        "refactor",
        "修复",
        "实现",
        "新增",
    )
    if any(marker in goal for marker in read_only_markers) and not any(
        marker in goal for marker in strong_edit_markers
    ):
        return False
    edit_markers = (
        "fix",
        "bug",
        "modify",
        "change",
        "update",
        "edit",
        "add",
        "implement",
        "refactor",
        "修复",
        "修改",
        "更新",
        "实现",
        "新增",
    )
    if any(marker in goal for marker in edit_markers):
        return True
    return task_type in {"simple_bugfix", "routine_coding", "complex_coding", "hard_bugfix", "large_refactor"}


def task_requests_project_verification(task: dict[str, Any]) -> bool:
    goal = str(task.get("user_goal", "")).lower()
    verification_markers = (
        "run tests",
        "run test",
        "run npm test",
        "run npm run check",
        "run pytest",
        "run vitest",
        "run playwright",
        "运行验证",
        "执行验证",
        "跑验证",
        "运行测试",
        "跑测试",
        "执行测试",
    )
    if any(marker in goal for marker in verification_markers):
        return True
    command_only_markers = ("npm test", "npm run check")
    command_reference_markers = (
        "输出",
        "列出",
        "建议",
        "推荐",
        "最小测试命令",
        "test_suggestions",
        "测试命令",
    )
    if any(marker in goal for marker in command_only_markers):
        return not any(marker in goal for marker in command_reference_markers)
    return False


def skip_project_verification_for_read_only_task(task: dict[str, Any], worker_result: Any) -> bool:
    policy = str(task.get("verification_policy") or "").lower()
    if policy in {"none", "changed_files_only"}:
        return not getattr(worker_result, "changed_files", [])
    if policy in {"unit", "full"}:
        return False
    return (
        not task_requires_diff(task)
        and not getattr(worker_result, "changed_files", [])
        and not task_requests_project_verification(task)
    )
