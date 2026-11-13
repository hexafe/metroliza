import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from threading import Event, get_ident
from unittest.mock import patch

import yaml

from metroliza.parsing.pdf_backend import require_pdf_backend
from metroliza.parsing.parser_profile_handoff import write_profile_validation_artifact
from metroliza.parsing import parser_profile_handoff as handoff_service

try:
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    from metroliza.ui.parser_plugin_wizard import (
        ParserPluginWizardDialog,
        create_llm_handoff_workspace,
        safe_profile_id,
        summarize_profile_store,
    )
    from metroliza.ui import detached_threads
    from modules.main_window import MainWindow
except ImportError as exc:  # pragma: no cover - environment-dependent import
    QApplication = None
    ParserPluginWizardDialog = None
    create_llm_handoff_workspace = None
    safe_profile_id = None
    summarize_profile_store = None
    MainWindow = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


def _write_pdf_text(path: Path, text: str) -> None:
    backend = require_pdf_backend()
    document = backend.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), text)
        document.save(str(path), garbage=4, deflate=True)
    finally:
        document.close()


def _wait_validation(dialog):
    deadline = monotonic() + 10
    while getattr(dialog, "_validation_thread", None) is not None and monotonic() < deadline:
        QTest.qWait(5)
    assert getattr(dialog, "_validation_thread", None) is None


def _wait_until(predicate):
    deadline = monotonic() + 10
    while not predicate() and monotonic() < deadline:
        QTest.qWait(5)
    assert predicate()


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 5, 12, tzinfo=timezone.utc).astimezone(tz)


class TestParserPluginWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if PYQT_IMPORT_ERROR is not None:
            raise unittest.SkipTest(f"PyQt6 is unavailable in this environment: {PYQT_IMPORT_ERROR}")
        cls.app = QApplication.instance() or QApplication([])

    def test_validation_artifact_and_status_match_original_service_literally(self):
        # The unchanged service is the independent synchronous oracle. Compare the
        # complete artifact at the same workspace, with the parser clock fixed.
        with tempfile.TemporaryDirectory() as home_dir, patch(
            "metroliza.parsing.declarative_parser_profiles.datetime", _FixedClock
        ):
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("literal_case")
                dialog.create_handoff_workspace()
                workspace = dialog.last_handoff_workspace
                original_profile = workspace.profile_path.read_bytes()
                workspace.expected_results_path.write_text("sample_file,reference\n", encoding="utf-8")
                for profile in (original_profile, b"{}\n", b"plugin: [\n"):
                    with self.subTest(profile=profile):
                        workspace.profile_path.write_bytes(profile)
                        output, passed = write_profile_validation_artifact(workspace)
                        self.assertIs(passed, profile == original_profile)
                        expected_bytes = output.read_bytes()
                        output.unlink()
                        dialog.validate_handoff_profile()
                        _wait_validation(dialog)
                        self.assertEqual(output.read_bytes(), expected_bytes)
                        self.assertEqual(
                            dialog.result_label.text(),
                            f"Validation {'passed' if passed else 'failed'}. Evidence: {output}",
                        )
                        self.assertEqual(dialog.result_label.property("statusVariant"), "success" if passed else "warning")
            finally:
                dialog.close()

    def test_default_validation_worker_repeat_stale_close_error_and_cleanup(self):
        original = handoff_service.validate_profile_handoff
        for outcome in ("success", "delayed", "error", "stale", "close", "accept", "reject", "delete"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as home_dir:
                dialog = ParserPluginWizardDialog(home=Path(home_dir))
                dialog.create_handoff_workspace()
                workspace = dialog.last_handoff_workspace
                workspace.expected_results_path.write_text("sample_file,reference\n", encoding="utf-8")
                entered, release = Event(), Event()
                calls = []

                def validate(request):
                    calls.append((get_ident(), request))
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("validation control expired")
                    if outcome == "error":
                        raise ValueError("synthetic validation failure")
                    return original(request)

                with patch.object(handoff_service, "validate_profile_handoff", validate):
                    try:
                        with patch("metroliza.ui.parser_plugin_wizard.monotonic",
                                   return_value=monotonic() - (2 if outcome == "delayed" else 0)):
                            dialog.validate_handoff_profile()
                        thread = dialog._validation_thread
                        _wait_until(entered.is_set)
                        self.assertNotEqual(calls[0][0], get_ident())
                        self.assertIs(calls[0][1], thread.workspace)
                        self.assertIsNot(thread.workspace, workspace)
                        self.assertFalse(dialog.validate_button.isEnabled())
                        self.assertEqual(dialog._validation_progress.isVisible(), outcome == "delayed")
                        self.assertEqual(dialog._validation_progress._delayed_show_timer.isActive(), outcome != "delayed")
                        dialog.validate_handoff_profile()
                        self.assertIs(dialog._validation_thread, thread)
                        self.assertEqual(len(calls), 1)
                        if outcome == "stale":
                            dialog.plugin_id_edit.setText("replacement")
                            dialog.create_handoff_workspace()
                        elif outcome in ("close", "accept", "reject"):
                            getattr(dialog, outcome)()
                        elif outcome == "delete":
                            dialog.deleteLater()
                            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                            self.assertTrue(sip.isdeleted(dialog))
                        label = None if outcome == "delete" else dialog.result_label.text()
                    finally:
                        release.set()
                        _wait_until(lambda: sip.isdeleted(thread))
                    self.assertNotIn(thread, detached_threads.running_threads())
                    if outcome == "delete":
                        self.assertTrue((workspace.root / "artifacts" / "profile_validation.txt").is_file())
                        continue
                    self.assertIsNone(dialog._validation_thread)
                    self.assertIsNone(dialog._validation_progress)
                    self.assertTrue(dialog.validate_button.isEnabled())
                    if outcome == "error":
                        self.assertEqual(dialog.result_label.text(), "synthetic validation failure")
                        self.assertEqual(dialog.result_label.property("statusVariant"), "warning")
                    elif outcome in ("success", "delayed"):
                        self.assertEqual(dialog.result_label.text(),
                                         f"Validation passed. Evidence: {workspace.root / 'artifacts/profile_validation.txt'}")
                    else:
                        self.assertEqual(dialog.result_label.text(), label)
                    dialog.close()

    def test_validation_custom_dispatch_stays_synchronous_and_propagates(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            dialog.create_handoff_workspace()
            workspace = dialog.last_handoff_workspace
            output = workspace.root / "custom.txt"
            with patch("metroliza.ui.parser_plugin_wizard.write_profile_validation_artifact",
                       return_value=(output, False)) as writer:
                dialog.validate_handoff_profile()
                writer.assert_called_once_with(workspace)
                self.assertIsNone(dialog._validation_thread)
                self.assertEqual(dialog.result_label.text(), f"Validation failed. Evidence: {output}")
            with patch("metroliza.ui.parser_plugin_wizard.write_profile_validation_artifact",
                       side_effect=ValueError("custom writer failed")):
                with self.assertRaisesRegex(ValueError, "custom writer failed"):
                    dialog.validate_handoff_profile()
            # Exact-type rejection precedes any new metadata-key equality callback.
            class Key(str):
                def __eq__(self, other):
                    raise AssertionError("custom key equality was consumed")

                __hash__ = str.__hash__

            workspace.__dict__[Key("unexpected")] = object()
            workspace.expected_results_path.write_text("sample_file,reference\n", encoding="utf-8")
            dialog.validate_handoff_profile()
            self.assertIsNone(dialog._validation_thread)
            self.assertIn("Validation passed", dialog.result_label.text())
            dialog.close()

    def test_custom_workspace_getter_retains_one_synchronous_dispatch(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            dialog.create_handoff_workspace()
            workspace = dialog.last_handoff_workspace
            workspace.expected_results_path.write_text("sample_file,reference\n", encoding="utf-8")
            calls = []

            def getter():
                calls.append("workspace")
                return workspace

            dialog._current_workspace = getter
            dialog.validate_handoff_profile()
            self.assertEqual(calls, ["workspace"])
            self.assertIsNone(dialog._validation_thread)
            self.assertEqual(dialog.result_label.text(),
                             f"Validation passed. Evidence: {workspace.root / 'artifacts/profile_validation.txt'}")
            dialog.close()

    def test_path_metaclass_declines_without_equality_hash_or_copy_callbacks(self):
        from pathlib import PosixPath
        for raising in (False, True):
            observations = []

            class PathMeta(type):
                def __eq__(cls, other):
                    observations.append("equality")
                    if raising:
                        raise AssertionError("path metaclass equality")
                    return False

                def __hash__(cls):
                    observations.append("hash")
                    raise AssertionError("path metaclass hash")

            class CustomPath(PosixPath, metaclass=PathMeta):
                def __copy__(self):
                    observations.append("copy")
                    raise AssertionError("path copy")

            with self.subTest(raising=raising), tempfile.TemporaryDirectory() as home_dir, patch(
                "metroliza.parsing.declarative_parser_profiles.datetime", _FixedClock,
            ):
                dialog = ParserPluginWizardDialog(home=Path(home_dir))
                try:
                    dialog.create_handoff_workspace()
                    workspace = dialog.last_handoff_workspace
                    workspace.expected_results_path.write_text("sample_file,reference\n", encoding="utf-8")
                    workspace = type(workspace)(workspace.root, workspace.profile_path,
                                                CustomPath(workspace.handoff_path), workspace.expected_results_path)
                    dialog.last_handoff_workspace = workspace
                    output, passed = write_profile_validation_artifact(workspace)
                    expected = output.read_bytes()
                    observations.clear()
                    dialog.validate_handoff_profile()
                    self.assertEqual(observations, [])
                    self.assertIsNone(getattr(dialog, "_validation_thread", None))
                    self.assertEqual(output.read_bytes(), expected)
                    self.assertEqual(dialog.result_label.text(),
                                     f"Validation {'passed' if passed else 'failed'}. Evidence: {output}")
                finally:
                    dialog.close()

    def test_validation_start_failure_releases_controls_and_thread(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            dialog.create_handoff_workspace()
            with patch("metroliza.ui.parser_plugin_wizard._ProfileValidationThread.start",
                       side_effect=RuntimeError("synthetic start failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic start failure"):
                    dialog.validate_handoff_profile()
            self.assertIsNone(dialog._validation_thread)
            self.assertIsNone(dialog._validation_progress)
            self.assertTrue(dialog.validate_button.isEnabled())
            self.assertFalse(detached_threads.running_threads())
            dialog.close()

    def test_native_application_quit_finishes_started_validation_with_identical_artifact(self):
        script = r'''
import sys
from pathlib import Path
from threading import Event, Timer
from time import monotonic
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from metroliza.app.gc_policy import install
from metroliza.parsing import parser_profile_handoff as service
from metroliza.ui import detached_threads
from metroliza.ui.parser_plugin_wizard import ParserPluginWizardDialog
app = QApplication([]); install(app); app.setQuitOnLastWindowClosed(False)
dialog = ParserPluginWizardDialog(home=Path(sys.argv[1])); dialog.create_handoff_workspace()
workspace = dialog.last_handoff_workspace
workspace.expected_results_path.write_text("sample_file,reference\n", encoding="utf-8")
output, passed = service.write_profile_validation_artifact(workspace)
assert passed
expected = output.read_bytes(); output.unlink()
entered, release = Event(), Event()
original = service.validate_profile_handoff
def validate(request):
    entered.set()
    assert release.wait(9), "native control expired"
    return original(request)
service.validate_profile_handoff = validate
def quit_after_start():
    if not entered.is_set():
        QTimer.singleShot(5, quit_after_start); return
    assert dialog._validation_thread.isRunning()
    assert detached_threads._QUIT_BLOCKERS[id(dialog._validation_thread)] is dialog._validation_thread
    print("actual validation work started", flush=True)
    Timer(5.2, release.set).start()
    app.quit()
closed, beats = [], []
original_finish = ParserPluginWizardDialog._finish_validation
def finish(owner, worker):
    original_finish(owner, worker)
    assert owner._validation_thread is None and "Validation passed" in owner.result_label.text()
    assert owner.close()
    closed.append(1)
    app.quit()
ParserPluginWizardDialog._finish_validation = finish
heartbeat = QTimer(); heartbeat.timeout.connect(lambda: beats.append(1)); heartbeat.start(10)
started = monotonic()
QTimer.singleShot(12000, lambda: app.exit(99))
QTimer.singleShot(0, dialog.validate_handoff_profile)
QTimer.singleShot(5, quit_after_start)
assert app.exec() == 0
assert closed == [1] and monotonic() - started > 5 and len(beats) > 100
assert entered.is_set() and release.is_set()
assert not detached_threads.running_threads()
assert output.read_bytes() == expected
print("STARTED -> QUIT -> FINISHED; artifact identical", len(expected), len(beats), flush=True)
'''
        with tempfile.TemporaryDirectory() as home_dir:
            child = subprocess.run([sys.executable, "-c", script, home_dir], capture_output=True, text=True, timeout=20)
        print("wizard actual child exit", child.returncode, child.stdout, child.stderr)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        self.assertIn("STARTED -> QUIT -> FINISHED; artifact identical", child.stdout)
        self.assertNotIn("QWaitCondition", child.stderr)

    def test_safe_profile_id_creates_parser_slug(self):
        self.assertEqual(safe_profile_id("Supplier Alpha v2"), "supplier_alpha_v2")
        self.assertEqual(safe_profile_id("123"), "supplier_123")
        self.assertEqual(safe_profile_id("a"), "a_profile")
        self.assertEqual(safe_profile_id(""), "supplier_profile")

    def test_create_handoff_workspace_writes_data_only_template(self):
        with tempfile.TemporaryDirectory() as home_dir:
            workspace = create_llm_handoff_workspace(
                plugin_id="Supplier Alpha",
                display_name="Supplier Alpha",
                source_format="pdf",
                home=Path(home_dir),
            )

            self.assertTrue(workspace.root.is_dir())
            self.assertTrue((workspace.root / "samples").is_dir())
            self.assertTrue(workspace.profile_path.is_file())
            self.assertTrue(workspace.handoff_path.is_file())
            self.assertTrue(workspace.expected_results_path.is_file())
            self.assertTrue((workspace.root / "handoff_manifest.json").is_file())
            self.assertTrue((workspace.root / "NON_TECHNICAL_STEPS.md").is_file())
            self.assertTrue((workspace.root / "contracts" / "01_parser_api_contract.md").is_file())
            self.assertTrue((workspace.root / "reference" / "contract_snippets.md").is_file())
            self.assertTrue((workspace.root / "prompts" / "01_identify_template_markers.md").is_file())
            self.assertTrue((workspace.root / "prompts" / "06_fix_validation_failures.md").is_file())

            profile_text = workspace.profile_path.read_text(encoding="utf-8")
            handoff_text = workspace.handoff_path.read_text(encoding="utf-8")
            manifest = json.loads((workspace.root / "handoff_manifest.json").read_text(encoding="utf-8"))
            snippets = (workspace.root / "reference" / "contract_snippets.md").read_text(encoding="utf-8")
            profile = yaml.safe_load(profile_text)
            self.assertEqual(profile["plugin"]["plugin_id"], "supplier_alpha")
            self.assertIn("source_format: pdf", profile_text)
            self.assertIn("Do not ask for Python code", handoff_text)
            self.assertIn("database writes", handoff_text)
            self.assertIn("measurement row capture names", handoff_text)
            self.assertIn("parser_plugin_self_service.py validate", handoff_text)
            self.assertIn("approval evidence records", handoff_text)
            self.assertEqual(manifest["package_type"], "declarative_profile")
            self.assertEqual(manifest["allowed_outputs"], ["profile.yaml"])
            self.assertIn("PluginManifest", snippets)
            self.assertIn("ParseResultV2", snippets)
            self.assertIn("Do not write SQLite", snippets)
            self.assertIn("sample_file,reference,report_date", workspace.expected_results_path.read_text(encoding="utf-8"))

    def test_store_summary_initializes_empty_store(self):
        with tempfile.TemporaryDirectory() as home_dir:
            summary = summarize_profile_store(home=Path(home_dir))

            self.assertEqual(summary.total, 0)
            self.assertEqual(summary.enabled, 0)
            self.assertTrue((summary.root / "approved").is_dir())
            self.assertTrue((summary.root / "incoming").is_dir())

    def test_dialog_can_create_handoff_workspace_without_llm_calls(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Beta")
                dialog.display_name_edit.setText("Supplier Beta")
                dialog.source_format_combo.setCurrentText("csv")

                dialog.create_handoff_workspace()

                expected_root = Path(home_dir) / ".metroliza" / "parser_plugins" / "profiles" / "incoming" / "supplier_beta"
                self.assertTrue(expected_root.is_dir())
                self.assertIn("Handoff folder ready", dialog.result_label.text())
                self.assertEqual(dialog.plugin_id_edit.text(), "supplier_beta")
                self.assertTrue(dialog.open_folder_button.isEnabled())
                self.assertTrue(dialog.copy_path_button.isEnabled())
                self.assertTrue(dialog.check_package_button.isEnabled())
                self.assertTrue(dialog.validate_button.isEnabled())
                self.assertTrue(dialog.repair_button.isEnabled())
            finally:
                dialog.close()

    def test_dialog_writes_integrity_validation_and_repair_artifacts(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Epsilon")
                dialog.create_handoff_workspace()

                dialog.check_handoff_package()
                self.assertIn("Package check passed", dialog.result_label.text())
                self.assertTrue(
                    (dialog.last_handoff_workspace.root / "artifacts" / "handoff_integrity.txt").is_file()
                )
                sample = dialog.last_handoff_workspace.root / "samples" / "sample_report_01.pdf"
                _write_pdf_text(
                    sample,
                    "\n".join(
                        (
                            "SUPPLIER TEMPLATE MARKER",
                            "Reference: REF123",
                            "Date: 2026-01-05",
                            "Sample: 0001",
                            "DIM X 10.0 0.1 -0.1 - 10.02 0.02 0",
                            "",
                        )
                    ),
                )
                dialog.last_handoff_workspace.expected_results_path.write_text(
                    "sample_file,reference,report_date,sample_number,block_index,header_normalized,"
                    "axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
                    "sample_report_01.pdf,REF123,2026-01-05,0001,0,MAIN FEATURE,Y,10.0,0.1,-0.1,,10.02,0.02,0\n",
                    encoding="utf-8",
                )

                dialog.validate_handoff_profile()
                _wait_validation(dialog)
                self.assertIn("Validation failed", dialog.result_label.text())
                self.assertTrue(
                    (dialog.last_handoff_workspace.root / "artifacts" / "profile_validation.txt").is_file()
                )

                dialog.create_repair_prompt()
                self.assertIn("Repair prompt written", dialog.result_label.text())
                self.assertTrue(
                    (dialog.last_handoff_workspace.root / "artifacts" / "profile_repair_prompt.md").is_file()
                )
            finally:
                dialog.close()

    def test_dialog_open_and_copy_handoff_folder_actions(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Gamma")
                dialog.create_handoff_workspace()

                with patch("metroliza.ui.parser_plugin_wizard.QDesktopServices.openUrl", return_value=True) as open_url:
                    dialog.open_handoff_folder()
                open_url.assert_called_once()

                dialog.copy_handoff_path()
                self.assertEqual(QApplication.clipboard().text(), str(dialog.last_handoff_workspace.root))
                self.assertIn("Copied handoff folder path", dialog.result_label.text())
            finally:
                dialog.close()

    def test_dialog_open_and_copy_are_noops_without_workspace(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                with patch("metroliza.ui.parser_plugin_wizard.QDesktopServices.openUrl") as open_url:
                    dialog.open_handoff_folder()
                dialog.copy_handoff_path()

                open_url.assert_not_called()
                self.assertIn("No handoff folder created yet", dialog.result_label.text())
            finally:
                dialog.close()

    def test_dialog_open_handoff_folder_reports_failed_desktop_open(self):
        with tempfile.TemporaryDirectory() as home_dir:
            dialog = ParserPluginWizardDialog(home=Path(home_dir))
            try:
                dialog.plugin_id_edit.setText("Supplier Delta")
                dialog.create_handoff_workspace()

                with patch("metroliza.ui.parser_plugin_wizard.QDesktopServices.openUrl", return_value=False):
                    dialog.open_handoff_folder()

                self.assertIn("Could not open folder", dialog.result_label.text())
                self.assertIn(str(dialog.last_handoff_workspace.root), dialog.result_label.text())
            finally:
                dialog.close()

    def test_main_window_tools_menu_opens_parser_profile_dialog(self):
        window = MainWindow(version_label="test", days_until_expiration=None)

        class FakeDialog:
            def __init__(self, parent):
                self.parent = parent
                self.show_calls = 0
                self.raise_calls = 0
                self.activate_calls = 0

            def isVisible(self):
                return self.show_calls > 0

            def show(self):
                self.show_calls += 1

            def raise_(self):
                self.raise_calls += 1

            def activateWindow(self):
                self.activate_calls += 1

        try:
            action_texts = [action.text() for action in window.tools_menu.actions()]
            self.assertIn("Parser profiles...", action_texts)

            with patch("metroliza.ui.parser_plugin_wizard.ParserPluginWizardDialog", FakeDialog):
                window.launch_parser_plugin_wizard()

            self.assertIsInstance(window.parser_plugin_wizard_dialog, FakeDialog)
            self.assertEqual(window.parser_plugin_wizard_dialog.show_calls, 1)
            self.assertEqual(window.parser_plugin_wizard_dialog.raise_calls, 1)
            self.assertEqual(window.parser_plugin_wizard_dialog.activate_calls, 1)
        finally:
            window.close()


def test_stale_completion_identity_preserves_current_request():
    from types import SimpleNamespace
    from metroliza.ui.parser_plugin_wizard import ParserPluginWizardDialog

    current, stale = object(), object()
    owner = SimpleNamespace(_validation_thread=current)
    ParserPluginWizardDialog._finish_validation(owner, stale)
    assert owner._validation_thread is current
