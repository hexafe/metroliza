import json
from pathlib import Path
import sys

from metroliza.app.diagnostic_launcher import run_with_store
from metroliza.shared.diagnostic_store import IncidentStore, StoreStatus


def test_real_exit_publishes_same_session_incident_and_selected_export(tmp_path):
    store = IncidentStore(tmp_path / "state")
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    delivery = run_with_store([sys.executable, str(child), "hard_exit"], store=store)
    assert delivery.observation.exit_code == 9
    assert delivery.storage_status is StoreStatus.SAVED
    listing = store.list_reports()
    assert listing.status is StoreStatus.AVAILABLE
    assert len(listing.reports) == 1
    loaded = store.load(listing.reports[0].report_id)
    assert loaded.incident.session_id.hex == delivery.observation.session_id
    assert json.loads(loaded.incident.events[0])["invocation_id"] == delivery.observation.session_id
    assert store.list_unclean_sessions().sessions == ()
    target = tmp_path / "chosen.zip"
    assert store.export(listing.reports[0].report_id, target).status is StoreStatus.EXPORTED
    import zipfile

    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {"incident.json", "manifest.json", "summary.json"}
        assert b"SYNTHETIC_RAW_SECRET" not in archive.read("incident.json")


def test_normal_observed_exit_has_only_clean_marker_and_no_crash_report(tmp_path):
    store = IncidentStore(tmp_path / "state")
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    delivery = run_with_store([sys.executable, str(child), "normal"], store=store)
    assert delivery.storage_status is StoreStatus.MARKER_CLEAN_ENDED
    assert not delivery.observation.needs_incident
    assert store.list_reports().reports == ()
    assert store.list_unclean_sessions().sessions == ()


def test_unavailable_store_does_not_change_child_result_or_use_cwd(tmp_path, monkeypatch):
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("synthetic", encoding="utf-8")
    store = IncidentStore(occupied)
    child = Path(__file__).parent / "fixtures" / "diagnostic_child.py"
    monkeypatch.chdir(tmp_path)
    delivery = run_with_store([sys.executable, str(child), "hard_exit"], store=store)
    assert delivery.observation.exit_code == 9
    assert delivery.storage_status is not StoreStatus.SAVED
    assert not (tmp_path / "metroliza.log").exists()
    assert not tuple(tmp_path.glob("incident-*"))
