"""One release identity through display, artifacts, wire and Windows metadata."""
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

import pytest

from metroliza.app.release_identity import ReleaseIdentity, launcher_identity, pe_resource_text
from metroliza.shared.diagnostic_events import (
    BuildPackager, DiagnosticEventValidationError, RuntimeMode, RuntimeProvenanceEvent,
)
from metroliza.shared.diagnostic_wire import decode_event, encode_event


@pytest.mark.parametrize("label, numeric", [
    ("0.8.0-dev.1", (0, 8, 0, 1)),
    ("0.8.0-rc.1", (0, 8, 0, 20001)),
    ("0.8.0", (0, 8, 0, 65535)),
])
def test_release_identity_drives_names_and_pe_projection(label, numeric):
    identity = ReleaseIdentity.parse(label)
    assert identity.label == label
    assert identity.pe_version == numeric
    assert identity.launcher_name == f"Metroliza-{label}-windows-x64.exe"
    assert identity.zip_name == f"Metroliza-{label}-windows-x64.zip"
    assert launcher_identity(identity.launcher_name) == (label, identity.folder_name)
    resource = pe_resource_text(identity)
    assert f"StringStruct('FileVersion', {label!r})" in resource
    assert f"StringStruct('ProductVersion', {label!r})" in resource
    assert f"filevers={numeric!r}, prodvers={numeric!r}" in resource


@pytest.mark.parametrize("label", [
    "0.8", "0.8.0-dev", "0.8.0-dev.0", "0.8.0-dev.01", "00.8.0", "0.8.0-rc.20000",
    "65536.0.0", "0.8.0+private", "0.8.0-dev.1\n", "../0.8.0-dev.1", "private-secret", None, True,
])
def test_invalid_or_unbounded_identity_is_rejected_without_reflecting_input(label):
    with pytest.raises(ValueError, match="^invalid release identity$"):
        ReleaseIdentity.parse(label)


def test_identity_constructor_rejects_hostile_channel_before_callbacks():
    class Hostile:
        def __eq__(self, other):
            raise AssertionError("callback must not run")

    with pytest.raises(ValueError, match="^invalid release identity$"):
        ReleaseIdentity(0, 8, 0, Hostile(), 1)


def test_legacy_artifact_identity_stays_exact():
    assert launcher_identity("metroliza_2026.09rc1_261119_launcher.exe") == (
        "2026.09rc1(261119)", "metroliza_2026.09rc1_261119",
    )
    with pytest.raises(ValueError):
        launcher_identity("Metroliza-0.8.0-dev.1-windows-x64.exe/secret")


def _event(**release):
    return RuntimeProvenanceEvent(uuid.uuid4(), uuid.uuid4(), 1, RuntimeMode.SOURCE,
                                  BuildPackager.SOURCE, **release)


@pytest.mark.parametrize("version", ["0.8.0-dev.1", "0.8.0-rc.2", "0.8.0"])
def test_new_provenance_wire_has_one_semver_without_fake_calendar_fields(version):
    event = _event(release_version=version)
    encoded = encode_event(event)
    assert encode_event(decode_event(encoded)) == encoded
    payload = json.loads(encoded)
    assert payload["release_version"] == version
    assert not {"release_year", "release_month", "release_candidate"} & payload.keys()


def test_historical_provenance_wire_roundtrip_is_byte_identical():
    event = _event(release_year=2026, release_month=9, release_candidate=1)
    encoded = encode_event(event)
    assert json.loads(encoded)["release_version"] == "2026.09rc1"
    assert encode_event(decode_event(encoded)) == encoded


@pytest.mark.parametrize("fields", [
    {"release_version": "0.8.0-dev.1", "release_year": 2026},
    {"release_version": "0.8.0-dev.1", "release_candidate": 1},
    {"release_version": "private-secret"},
    {"release_version": True},
])
def test_provenance_rejects_mixed_and_private_identity(fields):
    with pytest.raises(DiagnosticEventValidationError) as error:
        _event(**fields)
    assert "private-secret" not in str(error.value)


def test_canonical_and_compatibility_labels_have_no_pseudodate():
    import VersionDate
    from metroliza.app import version

    assert VersionDate.VERSION_LABEL == version.VERSION_LABEL == "0.8.0-dev.1"
    assert version.PUBLIC_VERSION_LABEL == version.RELEASE_VERSION == version.VERSION_LABEL
    assert version.VERSION_DATE == ""  # Deprecated import compatibility, never an artifact identity.


@pytest.mark.skipif(os.name != "nt", reason="actual PE resources require Windows")
def test_owned_stub_copy_has_actual_full_pe_identity(tmp_path: Path):
    from scripts.release_identity import stamp_stub, verify_pe

    # This verifies the actual pinned resource writer, separately from the canonical Rust build.
    source = tmp_path / "metroliza-launcher.exe"
    shutil.copy2(sys.executable, source)
    original = source.read_bytes()
    output = tmp_path / "versioned-stub.exe"
    identity = ReleaseIdentity.parse("0.8.0-dev.1")
    stamp_stub(source, output, identity)
    assert source.read_bytes() == original
    receipt = verify_pe(output, identity)
    assert receipt["FileVersion"] == receipt["ProductVersion"] == identity.label
    assert receipt["numeric_version"] == [0, 8, 0, 1]
