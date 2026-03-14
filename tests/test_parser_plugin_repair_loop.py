from modules.parser_plugin_repair_loop import build_repair_context, render_repair_prompt
from modules.parser_plugin_validation import ValidationCheck, ValidationReport


def test_build_repair_context_keeps_only_failed_checks():
    report = ValidationReport(
        plugin_id="demo",
        passed=False,
        checks=(
            ValidationCheck(name="ok", passed=True),
            ValidationCheck(name="fail_1", passed=False),
            ValidationCheck(name="fail_2", passed=False, detail="bad output"),
        ),
    )

    context = build_repair_context(report)
    assert context.plugin_id == "demo"
    assert tuple(check.name for check in context.failed_checks) == ("fail_1", "fail_2")


def test_render_repair_prompt_includes_failures_and_constraints():
    context = build_repair_context(
        ValidationReport(
            plugin_id="demo",
            passed=False,
            checks=(ValidationCheck(name="probe_returns_probe_result", passed=False, detail="returned str"),),
        ),
        guidance=("Use fixture-based parser extraction.",),
    )

    prompt = render_repair_prompt(context)

    assert "Repair request for parser plugin: demo" in prompt
    assert "probe_returns_probe_result (returned str)" in prompt
    assert "Do not change plugin_id." in prompt
    assert "Use fixture-based parser extraction." in prompt
