from __future__ import annotations

import json

from scripts import security_audit


def test_requirements_declare_all_runtime_import_packages():
    result = security_audit.audit_import_coverage(security_audit.REPO_ROOT)

    assert not result.errors


def test_security_audit_scans_canonical_source_tree():
    assert "src/metroliza" in security_audit.IMPORT_SCAN_DIRS
    assert "src/metroliza" in security_audit.BANDIT_SCAN_DIRS


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


def test_secret_scan_covers_supported_text_formats_without_echoing_values(tmp_path):
    secret_value = "AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    paths = []
    for index, suffix in enumerate(
        (
            ".py",
            ".yaml",
            ".toml",
            ".ini",
            ".json",
            ".env",
            ".env.production",
            ".cfg",
            ".conf",
            ".ps1",
            ".sh",
            ".txt",
            "",
        )
    ):
        name = suffix if suffix.startswith(".env") else f"config_{index}{suffix}"
        path = tmp_path / name
        path.write_text(f'client_secret = "{secret_value}"\n', encoding="utf-8")
        paths.append(name)

    result = security_audit.scan_secret_paths(tmp_path, paths, waivers={})

    assert len(result.errors) == len(paths)
    assert all(secret_value not in error for error in result.errors)


def test_secret_scan_checks_concrete_patterns_in_any_small_utf8_file(tmp_path):
    private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
    github_token = "ghp_" + ("A" * 30)
    paths_and_content = {
        "release-signing.pem": private_key_marker,
        "release-signing.key": private_key_marker,
        "Containerfile": github_token,
        "opaque.custom-extension": github_token,
    }
    for name, content in paths_and_content.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    result = security_audit.scan_secret_paths(
        tmp_path,
        paths_and_content,
        waivers={},
    )

    assert len(result.errors) == len(paths_and_content)
    assert all(
        content not in error
        for error in result.errors
        for content in paths_and_content.values()
    )


def test_secret_scan_fails_closed_for_invalid_text_candidate_in_ci_mode(tmp_path):
    candidate = tmp_path / "secrets.env"
    candidate.write_bytes(b"\xff\xfe\x00")

    local_result = security_audit.scan_secret_paths(
        tmp_path,
        (candidate.name,),
        waivers={},
    )
    ci_result = security_audit.scan_secret_paths(
        tmp_path,
        (candidate.name,),
        waivers={},
        fail_on_unreadable=True,
    )

    assert local_result.errors == []
    assert any("not valid UTF-8" in warning for warning in local_result.warnings)
    assert any("not valid UTF-8" in error for error in ci_result.errors)


def test_secret_scan_fails_closed_for_oversized_text_candidate_in_ci_mode(tmp_path):
    candidate = tmp_path / "secrets.env"
    candidate.write_bytes(b"x" * (security_audit.MAX_SECRET_SCAN_BYTES + 1))

    result = security_audit.scan_secret_paths(
        tmp_path,
        (candidate.name,),
        waivers={},
        fail_on_unreadable=True,
    )

    assert result.errors == [
        f"secrets.env: secret-scan text candidate exceeds "
        f"{security_audit.MAX_SECRET_SCAN_BYTES} byte limit"
    ]


def test_github_actions_environment_enables_strict_secret_scan(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert security_audit._running_in_ci() is True


def test_secret_scan_rejects_short_hex_and_marker_substring_credentials(tmp_path):
    secret_values = {
        "short.json": "A1!x",
        "hex.env": "0123456789abcdef0123456789abcdef",
        "short.env": "A1!x",
        "marker.toml": "sample-AbCdEf0123456789!",
    }
    for name, secret_value in secret_values.items():
        if name.endswith(".json"):
            text = json.dumps({"access_token": secret_value})
        elif name.endswith(".env"):
            text = f"access_token={secret_value}\n"
        else:
            text = f'access_token = "{secret_value}"\n'
        (tmp_path / name).write_text(text, encoding="utf-8")

    result = security_audit.scan_secret_paths(tmp_path, secret_values, waivers={})

    assert len(result.errors) == len(secret_values)
    assert all(
        secret_value not in error
        for error in result.errors
        for secret_value in secret_values.values()
    )


def test_secret_scan_preserves_explicit_placeholder_fixtures(tmp_path):
    placeholder_values = (
        "<redacted>",
        "YOUR_CLIENT_SECRET",
        "diagnostic-access-token",
        "json-secret",
        "secret123",
        "should-not-persist",
        "test-only-token",
        "${{ secrets.API_KEY }}",
        "{secret_value}",
        "abcdefghijklmnopqrstuvwxyz012345",
    )
    paths = []
    for index, placeholder_value in enumerate(placeholder_values):
        name = f"placeholder_{index}.json"
        (tmp_path / name).write_text(
            json.dumps({"access_token": placeholder_value}),
            encoding="utf-8",
        )
        paths.append(name)

    result = security_audit.scan_secret_paths(tmp_path, paths, waivers={})

    assert result.errors == []


def test_secret_scan_ignores_python_runtime_credential_expressions(tmp_path):
    source_path = tmp_path / "runtime.py"
    source_path.write_text(
        "access_token = credentials.token\n"
        "refresh_token = token_payload.get('refresh_token')\n"
        "password = env_password\n",
        encoding="utf-8",
    )

    result = security_audit.scan_secret_paths(tmp_path, (source_path.name,), waivers={})

    assert result.errors == []


def test_secret_scan_allows_only_fixture_or_example_waivers(tmp_path):
    result = security_audit.scan_secret_paths(
        tmp_path,
        (),
        waivers={"src/metroliza/runtime.py": "too noisy"},
    )

    assert result.errors == [
        "Secret-scan waiver must be fixture/example-only: "
        "src/metroliza/runtime.py (too noisy)"
    ]


def test_secret_scan_ignores_deleted_blocked_credential_paths(tmp_path):
    result = security_audit.scan_secret_paths(
        tmp_path,
        ("config/token.json", "config/credentials.json"),
        waivers={},
    )

    assert result.errors == []


def test_secret_scan_blocks_suffixed_credential_filenames(tmp_path):
    credential_path = tmp_path / "customer.token.json"
    credential_path.write_text("{}", encoding="utf-8")

    result = security_audit.scan_secret_paths(
        tmp_path,
        (credential_path.name,),
        waivers={},
    )

    assert result.errors == [
        "customer.token.json: filename is reserved for untracked credentials"
    ]


def test_ci_bandit_medium_gate_accepts_only_reviewed_unexpired_fingerprints(tmp_path):
    source_path = tmp_path / "src" / "query.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("query = f'SELECT {column}'\n", encoding="utf-8")
    finding = {
        "filename": str(source_path),
        "line_number": 1,
        "test_id": "B608",
        "issue_severity": "MEDIUM",
        "issue_text": "Possible SQL injection vector",
        "code": "1 query = f'SELECT {column}'\n",
    }
    fingerprint = security_audit.bandit_issue_fingerprint(
        tmp_path,
        finding,
        repository="metroliza",
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "repository": "metroliza",
                        "fingerprint": fingerprint,
                        "test_id": "B608",
                        "path": "src/query.py",
                        "owner": "Security",
                        "rationale": "Identifier is allowlisted before interpolation.",
                        "expires_on": "2099-12-31",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    accepted = security_audit._audit_medium_bandit_results(
        tmp_path,
        [finding],
        repository="metroliza",
        baseline_path=baseline_path,
    )
    changed = dict(finding, code="1 query = f'DELETE {column}'\n")
    rejected = security_audit._audit_medium_bandit_results(
        tmp_path,
        [changed],
        repository="metroliza",
        baseline_path=baseline_path,
    )

    assert accepted.errors == []
    assert accepted.warnings
    assert any("Unbaselined Bandit medium finding" in error for error in rejected.errors)
