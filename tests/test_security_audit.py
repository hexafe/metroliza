from __future__ import annotations

from scripts import security_audit


def test_requirements_declare_all_runtime_import_packages():
    result = security_audit.audit_import_coverage(security_audit.REPO_ROOT)

    assert not result.errors


def test_internal_hexafe_dependencies_are_full_sha_pins():
    result = security_audit.audit_internal_dependency_pins(security_audit.REPO_ROOT, sibling_root=None)

    errors_without_checkout = [
        error for error in result.errors if "Sibling repo" not in error and "checkout" not in error
    ]
    assert not errors_without_checkout


def test_security_tool_dependencies_are_declared():
    packages = security_audit.declared_packages(security_audit.REPO_ROOT)

    assert security_audit.normalize_package_name("Pillow") in packages
    assert security_audit.normalize_package_name("pip-audit") in packages
    assert security_audit.normalize_package_name("bandit") in packages


def test_public_audit_requirements_exclude_internal_git_pins():
    lines, warnings = security_audit.build_public_audit_requirements(
        security_audit.REPO_ROOT, sibling_root=None
    )
    joined = "\n".join(lines)

    assert "git+https://github.com/hexafe" not in joined
    assert "hexafe-groupstats" not in joined
    assert "hexafe-plotstats" not in joined
    assert "oznak" not in joined
    assert "Pillow>=12.2.0" in lines
    assert warnings
