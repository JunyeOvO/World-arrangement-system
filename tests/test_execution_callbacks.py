from __future__ import annotations

from types import SimpleNamespace

from orchestrator.execution_callbacks import ExecutionCallbackAdapter


class FakeLifecycle:
    def __init__(self):
        self.statuses = []

    def set_status(self, task_id, status, event_type, payload):
        self.statuses.append((task_id, status, event_type, payload))


class FakePolicyLearning:
    def __init__(self):
        self.calls = []

    def record_task_completion(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class FakePermissionAuditor:
    def __init__(self):
        self.declared = []
        self.diff = []

    def check_declared_permissions(self, task_id, worker_name, task):
        self.declared.append((task_id, worker_name, task))
        return {"allowed": True}

    def check_diff_permissions(self, task_id, worker_name, changed_files):
        self.diff.append((task_id, worker_name, changed_files))
        return {"allowed": False}


class FakeAttemptMetrics:
    def __init__(self):
        self.metrics = []
        self.ledgers = []

    def write_attempt_metrics(self, *args, **kwargs):
        self.metrics.append((args, kwargs))

    def write_token_ledger(self, task_id):
        self.ledgers.append(task_id)


class FakeStaleReaper:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def reap(self, task):
        self.calls.append(task)
        return self.result


def _adapter(reap_result=None):
    lifecycle = FakeLifecycle()
    policy = FakePolicyLearning()
    permissions = FakePermissionAuditor()
    metrics = FakeAttemptMetrics()
    reaper = FakeStaleReaper(reap_result)
    adapter = ExecutionCallbackAdapter(
        lifecycle=lifecycle,
        policy_learning=policy,
        permission_auditor=permissions,
        attempt_metrics=metrics,
        stale_worker_reaper=reaper,
    )
    return adapter, lifecycle, policy, permissions, metrics, reaper


def test_execution_callbacks_delegate_status_policy_permissions_and_metrics():
    adapter, lifecycle, policy, permissions, metrics, _ = _adapter()
    task = {"task_id": "t_cb", "project_id": "p", "risk_level": "low"}
    project = {"repo": "C:/repo"}

    adapter.set_status("t_cb", "ROUTED", "routed", {"worker": "claude_code"})
    adapter.record_policy_learning(task, project, success=True, worker="claude_code", changed_paths=["a.py"])
    declared = adapter.check_worker_declared_permissions("t_cb", "claude_code", {"target_paths": ["a.py"]})
    diff = adapter.check_worker_diff_permissions("t_cb", "claude_code", [".env"])
    adapter.write_attempt_metrics("t_cb", 1, {"worker": "claude_code"}, SimpleNamespace(status="success"), None)
    adapter.write_token_ledger("t_cb")

    assert lifecycle.statuses == [("t_cb", "ROUTED", "routed", {"worker": "claude_code"})]
    assert policy.calls[-1][0][2] is True
    assert policy.calls[-1][1]["changed_paths"] == ["a.py"]
    assert declared == {"allowed": True}
    assert diff == {"allowed": False}
    assert permissions.declared[-1][0:2] == ("t_cb", "claude_code")
    assert permissions.diff[-1] == ("t_cb", "claude_code", [".env"])
    assert metrics.metrics
    assert metrics.ledgers == ["t_cb"]


def test_execution_callbacks_apply_stale_reaper_transition():
    reap_result = SimpleNamespace(status="COMPLETED_WITH_ARTIFACTS", event_type="stale_worker_reaped", payload={"source": "test"})
    adapter, lifecycle, _, _, _, reaper = _adapter(reap_result)
    task = {"task_id": "t_stale"}

    adapter.reap_stale_worker_task(task)

    assert reaper.calls == [task]
    assert lifecycle.statuses == [
        ("t_stale", "COMPLETED_WITH_ARTIFACTS", "stale_worker_reaped", {"source": "test"})
    ]
