from orchestrator.risk_policy import check_changed_files, evaluate_task, scan_command


def test_auto_merge_forbidden():
    result = evaluate_task("fix bug", auto_merge=True)
    assert not result.allowed


def test_forbidden_path_changed():
    result = check_changed_files(["src/app.py", ".env"])
    assert not result.allowed


def test_forbidden_command_detected():
    result = scan_command("git push --force origin main")
    assert not result.allowed

