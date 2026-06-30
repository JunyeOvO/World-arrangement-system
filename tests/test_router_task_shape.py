from types import SimpleNamespace

from orchestrator.router_task_shape import classify_task_shape, is_read_only_task
from orchestrator.router_v3 import classify_task_shape as legacy_classify_task_shape


def test_router_v3_keeps_legacy_classify_import():
    task = {"user_goal": "Update README", "target_paths": ["README.md"]}

    assert legacy_classify_task_shape(task) == "docs_update"


def test_read_only_protocol_overrides_explicit_patch_shape():
    task = {
        "user_goal": "Investigate config drift, do not edit files.",
        "task_shape": "targeted_patch",
        "task_mode": "read_only",
        "expected_diff": False,
    }

    assert is_read_only_task(task)
    assert classify_task_shape(task) == "review_only"


def test_read_only_multimodal_task_keeps_multimodal_analysis_shape():
    task = {"user_goal": "Analyze this screenshot only", "task_mode": "read_only"}
    features = SimpleNamespace(requires_multimodal=True)

    assert classify_task_shape(task, features=features) == "multimodal_analysis"


def test_multimodal_with_code_change_becomes_multimodal_to_code():
    task = {"user_goal": "Use this screenshot to fix the UI layout"}
    features = SimpleNamespace(requires_multimodal=True)
    labels = SimpleNamespace(needs_code_change=True)

    assert classify_task_shape(task, features=features, labels=labels) == "multimodal_to_code"


def test_config_path_becomes_config_repair():
    task = {
        "user_goal": "Fix project settings",
        "target_paths": ["config/projects.yaml"],
    }

    assert classify_task_shape(task) == "config_repair"


def test_test_failure_investigation_is_not_test_generation():
    task = {"user_goal": "Investigate why test runs are failing in CI"}

    assert classify_task_shape(task) != "test_generation"


def test_add_unit_tests_is_test_generation():
    task = {"user_goal": "Add unit tests for router behavior"}

    assert classify_task_shape(task) == "test_generation"


def test_open_bug_hunt_requires_no_target_paths():
    assert classify_task_shape({"user_goal": "Find one bug and fix it"}) == "open_bug_hunt"
    assert (
        classify_task_shape(
            {
                "user_goal": "Find one bug and fix it",
                "target_paths": ["app/ranker.py"],
            }
        )
        == "targeted_patch"
    )


def test_needs_code_change_label_defaults_to_targeted_patch():
    labels = SimpleNamespace(needs_code_change=True)

    assert classify_task_shape({"user_goal": "Improve behavior"}, labels=labels) == "targeted_patch"
