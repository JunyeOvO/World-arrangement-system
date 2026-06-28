from pathlib import Path

from orchestrator.pr import create_pr_or_patch


def test_create_pr_or_patch_reports_no_changes_for_empty_diff(tmp_path: Path):
    diff = tmp_path / "diff.patch"
    diff.write_text("", encoding="utf-8")

    result = create_pr_or_patch(
        tmp_path,
        "branch",
        "main",
        "title",
        tmp_path / "body.md",
        diff,
        allow_remote_push=False,
    )

    assert result.status == "COMPLETED_NO_CHANGES"


def test_create_pr_or_patch_reports_patch_when_diff_exists(tmp_path: Path):
    diff = tmp_path / "diff.patch"
    diff.write_text("diff --git a/a b/a\n", encoding="utf-8")

    result = create_pr_or_patch(
        tmp_path,
        "branch",
        "main",
        "title",
        tmp_path / "body.md",
        diff,
        allow_remote_push=False,
    )

    assert result.status == "COMPLETED_WITH_PATCH"
