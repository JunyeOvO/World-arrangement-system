"""Phase 6 tests: Sensitive keywords → WARN only, non-reversible commands → BLOCK."""
from orchestrator.risk_policy import evaluate_task, RiskResult


def test_fix_auth_bug_is_warning_not_blocked():
    """'fix auth token refresh bug' should produce warnings, not blocking issues."""
    result = evaluate_task("fix auth token refresh bug")
    assert result.allowed, f"Should be allowed, got issues: {result.blocking_issues}"
    assert len(result.warnings) > 0
    assert any("auth" in w for w in result.warnings)


def test_add_payment_ui_is_warning_not_blocked():
    """'add payment UI' should be WARN only."""
    result = evaluate_task("add payment method dropdown UI")
    assert result.allowed
    assert any("payment" in w for w in result.warnings)


def test_update_product_page_does_not_match_prod_block():
    """'update product list page' should NOT match 'prod' (word boundary check)."""
    result = evaluate_task("update product list page")
    assert result.allowed
    # "product" should not trigger "prod" keyword
    prod_warnings = [w for w in result.warnings if "prod" in w.lower() and "product" not in w.lower()]
    assert len(prod_warnings) == 0, f"product should not match prod: {prod_warnings}"


def test_fix_deploy_script_typo_is_warning_not_blocked():
    """'fix deploy script typo' should be WARN only."""
    result = evaluate_task("fix deploy script typo in CI")
    assert result.allowed
    assert any("deploy" in w for w in result.warnings)


def test_password_reset_template_is_warning_not_blocked():
    """'修复密码重置邮件模板样式' should be WARN only."""
    result = evaluate_task("修复密码重置邮件模板的样式")
    assert result.allowed
    assert len(result.warnings) > 0


def test_rm_rf_root_is_blocked():
    """'rm -rf /' should still be BLOCKED."""
    result = evaluate_task("run rm -rf / on the server")
    assert not result.allowed
    assert len(result.blocking_issues) > 0
    assert any("rm -rf" in i for i in result.blocking_issues)


def test_git_push_force_is_blocked():
    """'git push --force' should still be BLOCKED."""
    result = evaluate_task("git push --force origin main")
    assert not result.allowed
    assert len(result.blocking_issues) > 0


def test_dangerously_skip_permissions_is_blocked():
    """'--dangerously-skip-permissions' should still be BLOCKED."""
    result = evaluate_task("run with --dangerously-skip-permissions flag")
    assert not result.allowed
    assert len(result.blocking_issues) > 0


def test_drop_database_is_blocked():
    """'drop database' should still be BLOCKED."""
    result = evaluate_task("drop database production")
    assert not result.allowed
    assert len(result.blocking_issues) > 0


def test_truncate_is_blocked():
    """'truncate' should still be BLOCKED."""
    result = evaluate_task("truncate the users table")
    assert not result.allowed
    assert len(result.blocking_issues) > 0


def test_normal_task_no_warnings_or_issues():
    """A vanilla task should have no issues and no warnings."""
    result = evaluate_task("add unit tests for the user model")
    assert result.allowed
    assert len(result.blocking_issues) == 0
    # No sensitive keywords should match
    has_sensitive = any(
        kw in result.warnings for kw in ["auth", "payment", "deploy", "prod", "password"]
    )
    assert not has_sensitive


def test_auto_merge_still_blocked():
    """auto_merge=true should still be BLOCKED in V1."""
    result = evaluate_task("fix a bug", auto_merge=True)
    assert not result.allowed
    assert any("auto_merge" in i for i in result.blocking_issues)
