from __future__ import annotations

import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class CommandResult:
    command: str
    returncode: int
    log_path: str
    duration_sec: float
    kind: str = "verify"


@dataclass
class VerifyResult:
    tests_passed: bool
    build_passed: bool
    command_results: list[CommandResult] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    diff_path: str | None = None
    forbidden_allowed: bool = True
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tests_passed": self.tests_passed,
            "build_passed": self.build_passed,
            "forbidden_allowed": self.forbidden_allowed,
            "commands": [asdict(result) for result in self.command_results],
            "command_results": [asdict(result) for result in self.command_results],
            "changed_files": list(self.changed_files),
            "diff_path": self.diff_path,
            "finished_at": self.finished_at,
        }


def run_commands(
    worktree: Path,
    commands: Iterable[str],
    log_path: Path,
    timeout: int = 1200,
    kind: str = "verify",
) -> list[CommandResult]:
    results: list[CommandResult] = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for command in commands:
        start = time.monotonic()
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n$ {command}\n")
            proc = subprocess.run(
                command,
                cwd=worktree,
                shell=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        results.append(CommandResult(command, proc.returncode, str(log_path), time.monotonic() - start, kind))
        if proc.returncode != 0:
            break
    return results


def changed_files(worktree: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(worktree), "diff", "--name-only"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def make_diff(worktree: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "-C", str(worktree), "diff", "--binary"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
        check=False,
    )
    output.write_text(proc.stdout or "", encoding="utf-8")
    return output


def verify(worktree: Path, test_commands: list[str], build_commands: list[str], verify_dir: Path) -> VerifyResult:
    test_results = run_commands(worktree, test_commands, verify_dir / "test.log", kind="test") if test_commands else []
    tests_passed = all(r.returncode == 0 for r in test_results)
    build_results = run_commands(worktree, build_commands, verify_dir / "build.log", kind="build") if build_commands else []
    build_passed = all(r.returncode == 0 for r in build_results)
    diff = make_diff(worktree, verify_dir / "diff.patch")
    files = changed_files(worktree)
    return VerifyResult(
        tests_passed,
        build_passed,
        [*test_results, *build_results],
        files,
        str(diff),
        True,
        _now(),
    )


def write_verify_result(result: VerifyResult, output: Path) -> Path:
    import json

    output.parent.mkdir(parents=True, exist_ok=True)
    if not result.finished_at:
        result.finished_at = _now()
    output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
