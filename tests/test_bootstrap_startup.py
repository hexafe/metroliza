import os
import io
import json
import logging
import uuid

import pytest
from pathlib import Path
import subprocess
import sys
import unittest
import types
from unittest.mock import patch

import metroliza
from metroliza.app import bootstrap
from metroliza.app.startup_splash import (
    close_bootloader_splash,
    should_show_startup_splash,
    update_bootloader_splash,
)
from modules.license_bootstrap import validate_license_bootstrap


class TestBootstrapStartup(unittest.TestCase):
    def test_package_imports_from_outside_repo_root(self):
        repo_root = Path(__file__).resolve().parents[1]
        src_dir = repo_root / "src"
        with self.subTest("installed-package-style import"):
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import metroliza; "
                        "from metroliza.app import bootstrap; "
                        "print(metroliza.STARTUP_SMOKE_ENV); "
                        "print(bootstrap.STARTUP_SMOKE_ENV)"
                    ),
                ],
                cwd=repo_root.parent,
                env={**os.environ, "PYTHONPATH": str(src_dir)},
                text=True,
                capture_output=True,
                check=True,
            )

        self.assertEqual(result.stdout.splitlines(), ["METROLIZA_STARTUP_SMOKE"] * 2)

    def test_root_launcher_import_keeps_package_submodules_available(self):
        repo_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import metroliza; "
                    "from metroliza.app import bootstrap; "
                    "print(metroliza.STARTUP_SMOKE_ENV); "
                    "print(bootstrap.__file__)"
                ),
            ],
            cwd=repo_root,
            env={**os.environ, "PYTHONPATH": f"{repo_root / 'src'}{os.pathsep}{repo_root}"},
            text=True,
            capture_output=True,
            check=True,
        )

        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "METROLIZA_STARTUP_SMOKE")
        self.assertIn("src/metroliza/app/bootstrap.py", lines[1].replace("\\", "/"))

    def test_launch_ui_creates_qapplication_before_importing_main_window(self):
        call_order = []
        app_state = {"created": False}

        class FakeApplication:
            @staticmethod
            def instance():
                return None

            def __init__(self, argv):
                app_state["created"] = True
                call_order.append("qapplication_created")

            def exec(self):
                call_order.append("app_exec")
                return 0

        class FakeMainWindow:
            def __init__(self, version_label, days_until_expiration):
                call_order.append("main_window_init")

            def show(self):
                call_order.append("main_window_show")

            def schedule_feature_import_warmup(
                self,
                *,
                delay_ms=100,
                on_finished=None,
                status_callback=None,
            ):
                call_order.append(f"main_window_schedule:{delay_ms}")
                if status_callback is not None:
                    status_callback("Loading tools...")
                if on_finished is not None:
                    on_finished()

        fake_qtwidgets = types.SimpleNamespace(QApplication=FakeApplication)
        def unexpected_hardware_id():
            raise AssertionError("hardware ID should not be generated when license checks are disabled")

        fake_license_manager = types.SimpleNamespace(generate_hardware_id=unexpected_hardware_id)
        fake_license_module = types.SimpleNamespace(LicenseKeyManager=fake_license_manager)
        real_import = __import__

        def tracked_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "PyQt6.QtWidgets":
                call_order.append("import_qtwidgets")
                return fake_qtwidgets
            if name == "metroliza.app.license_key_manager":
                call_order.append("import_license_manager")
                return fake_license_module
            return real_import(name, globals, locals, fromlist, level)

        def load_main_window_factory():
            call_order.append("import_main_window")
            self.assertTrue(app_state["created"])
            return FakeMainWindow

        config = bootstrap.StartupConfig(
            startup_smoke_mode=False,
            startup_ui_smoke_mode=False,
            pdf_parser_smoke_fixture=None,
            pdf_parser_smoke_expected_text=None,
            license_verification_enabled=False,
        )

        fake_splash = types.SimpleNamespace(
            show_message=lambda *_args, **_kwargs: None,
            close=lambda: None,
            finish=lambda _widget: call_order.append("splash_finish"),
        )

        with patch("builtins.__import__", side_effect=tracked_import), patch(
            "metroliza.app.bootstrap.validate_license_bootstrap",
            return_value=types.SimpleNamespace(is_valid=True, days_until_expiration=7),
        ), patch(
            "metroliza.app.bootstrap.create_startup_splash",
            return_value=fake_splash,
        ), patch(
            "metroliza.app.bootstrap.load_main_window_factory",
            side_effect=load_main_window_factory,
        ):
            result = bootstrap.launch_ui(config)

        self.assertEqual(result, 0)
        self.assertEqual(
            call_order,
            [
                "import_qtwidgets",
                "qapplication_created",
                "import_main_window",
                "main_window_init",
                "main_window_show",
                "main_window_schedule:0",
                "splash_finish",
                "app_exec",
            ],
        )

    def test_load_startup_config_defaults_to_license_verification_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            config = bootstrap.load_startup_config()

        self.assertFalse(config.startup_smoke_mode)
        self.assertFalse(config.startup_ui_smoke_mode)
        self.assertIsNone(config.pdf_parser_smoke_fixture)
        self.assertIsNone(config.pdf_parser_smoke_expected_text)
        self.assertFalse(config.license_verification_enabled)

    def test_load_startup_config_can_disable_license_verification(self):
        with patch.dict(
            "os.environ",
            {
                metroliza.LICENSE_MODE_ENV: "false",
                metroliza.STARTUP_SMOKE_ENV: "0",
                "METROLIZA_STARTUP_UI_SMOKE": "1",
            },
            clear=True,
        ):
            config = bootstrap.load_startup_config()

        self.assertFalse(config.license_verification_enabled)
        self.assertTrue(config.startup_ui_smoke_mode)

    def test_startup_splash_auto_disables_for_offscreen_ui_smoke(self):
        with patch.dict(
            "os.environ",
            {
                "METROLIZA_STARTUP_UI_SMOKE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            },
            clear=True,
        ):
            self.assertFalse(should_show_startup_splash(ui_smoke_mode=True))

    def test_startup_splash_can_be_forced_for_smoke(self):
        with patch.dict(
            "os.environ",
            {
                "METROLIZA_STARTUP_SPLASH": "1",
                "METROLIZA_STARTUP_UI_SMOKE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            },
            clear=True,
        ):
            self.assertTrue(should_show_startup_splash(ui_smoke_mode=True))

    def test_bootloader_splash_helpers_update_and_close_when_available(self):
        calls = []

        fake_pyi_splash = types.SimpleNamespace(
            is_alive=lambda: True,
            update_text=lambda message: calls.append(("update", message)),
            close=lambda: calls.append(("close", None)),
        )

        with patch.dict("sys.modules", {"pyi_splash": fake_pyi_splash}):
            update_bootloader_splash("Loading dashboard...", phase="test")
            close_bootloader_splash(phase="test")

        self.assertEqual(
            calls,
            [
                ("update", "Loading dashboard..."),
                ("close", None),
            ],
        )

    def test_bootloader_splash_helpers_are_noop_when_unavailable(self):
        with patch.dict("sys.modules", {"pyi_splash": None}):
            update_bootloader_splash("Loading dashboard...", phase="test")
            close_bootloader_splash(phase="test")

    def test_validate_license_bootstrap_skips_validation_when_disabled(self):
        with patch("metroliza.app.license_bootstrap.verify_license") as verify_mock:
            result = validate_license_bootstrap(False)

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.days_until_expiration)
        verify_mock.assert_not_called()

    def test_validate_license_bootstrap_invalid_key_when_enabled(self):
        with patch("metroliza.app.license_bootstrap.verify_license", return_value=False):
            result = validate_license_bootstrap(True)

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.days_until_expiration)

    def test_validate_license_bootstrap_valid_enabled_returns_expiration_days(self):
        manager_calls = []
        fake_manager = types.SimpleNamespace(
            read_license_key_file=lambda: manager_calls.append("read") or "license-token"
        )
        fake_module = types.SimpleNamespace(LicenseKeyManager=fake_manager)

        with patch("metroliza.app.license_bootstrap.verify_license", return_value=True), patch(
            "metroliza.app.license_bootstrap.get_days_until_expiration", return_value=12
        ), patch.dict(
            "sys.modules",
            {
                "modules.license_key_manager": fake_module,
                "metroliza.app.license_key_manager": fake_module,
            },
        ):
            result = validate_license_bootstrap(True)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.days_until_expiration, 12)
        self.assertEqual(manager_calls, ["read"])

    def test_bootstrap_application_uses_smoke_mode_when_enabled(self):
        smoke_config = bootstrap.StartupConfig(
            startup_smoke_mode=True,
            startup_ui_smoke_mode=False,
            pdf_parser_smoke_fixture=None,
            pdf_parser_smoke_expected_text=None,
            license_verification_enabled=True,
        )
        with patch("metroliza.app.bootstrap.initialize_logging") as init_logging, patch(
            "metroliza.app.bootstrap.load_startup_config", return_value=smoke_config
        ), patch("metroliza.app.bootstrap.run_startup_smoke_mode", return_value=0) as smoke_mode, patch(
            "metroliza.app.bootstrap.launch_ui"
        ) as launch_ui:
            result = bootstrap.bootstrap_application()

        self.assertEqual(result, 0)
        smoke_mode.assert_called_once_with(init_logging.return_value)
        launch_ui.assert_not_called()



    def test_bootstrap_application_uses_pdf_parser_smoke_when_fixture_is_set(self):
        smoke_config = bootstrap.StartupConfig(
            startup_smoke_mode=False,
            startup_ui_smoke_mode=False,
            pdf_parser_smoke_fixture='tests/fixtures/pdf/cmm_smoke_fixture.pdf',
            pdf_parser_smoke_expected_text='METROLIZA PDF PARSER SMOKE',
            license_verification_enabled=True,
        )
        with patch("metroliza.app.bootstrap.initialize_logging") as init_logging, patch(
            "metroliza.app.bootstrap.load_startup_config", return_value=smoke_config
        ), patch(
            "metroliza.app.bootstrap.run_pdf_parser_smoke_mode", return_value=0
        ) as parser_smoke_mode, patch(
            "metroliza.app.bootstrap.launch_ui"
        ) as launch_ui:
            result = bootstrap.bootstrap_application()

        self.assertEqual(result, 0)
        parser_smoke_mode.assert_called_once_with(
            init_logging.return_value,
            'tests/fixtures/pdf/cmm_smoke_fixture.pdf',
            'METROLIZA PDF PARSER SMOKE',
        )
        launch_ui.assert_not_called()

    def test_run_application_logs_and_returns_error_on_startup_exception(self):
        error = RuntimeError("startup failure")
        with patch("metroliza.app.bootstrap.bootstrap_application", side_effect=error), patch(
            "metroliza.app.bootstrap.log_and_exit"
        ) as log_and_exit:
            result = bootstrap.run_application()

        self.assertEqual(result, 1)
        log_and_exit.assert_called_once_with(error)


if __name__ == "__main__":
    unittest.main()


@pytest.fixture
def startup_trace(tmp_path, monkeypatch):
    """Actual managed files/stream and bootstrap control flow; only GUI/domain stand-ins."""
    from metroliza.shared import logging_utils

    home, cwd = tmp_path / "home", tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    logger = logging.Logger("metroliza.startup-test", logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    monkeypatch.setattr(logging, "getLogger", lambda *args: logger)
    monkeypatch.setattr(logging_utils.Path, "home", lambda: home)
    monkeypatch.setattr(logging_utils.Path, "cwd", lambda: cwd)
    monkeypatch.setattr(sys, "stderr", stream)
    for name in (
        bootstrap.STARTUP_SMOKE_ENV, bootstrap.PDF_PARSER_SMOKE_FIXTURE_ENV,
        bootstrap.PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV, bootstrap.LICENSE_MODE_ENV,
        "METROLIZA_STARTUP_UI_SMOKE", "METROLIZA_STARTUP_PROFILE",
        "METROLIZA_LOG_LEVEL", "METROLIZA_FILE_LOG_LEVEL", "METROLIZA_CONSOLE_LOG_LEVEL",
        "METROLIZA_SUPPORT_BUILD",
    ):
        monkeypatch.delenv(name, raising=False)
    config = logging_utils.LoggingConfig(logging.INFO, logging.INFO, logging.INFO)
    def setup():
        return logging_utils.ensure_application_logging(config=config)
    monkeypatch.setattr(bootstrap, "ensure_application_logging", setup)
    setup()
    state = {"calls": [], "exit_code": 0, "caught": [], "valid_license": True}

    class Application:
        def exec(self):
            state["calls"].append("exec")
            return state["exit_code"]

        def processEvents(self):
            state["calls"].append("process_events")

    class Window:
        def __init__(self, *args):
            state["calls"].append("construct")

        def show(self):
            state["calls"].append("show")

        def schedule_feature_import_warmup(self, **kwargs):
            state["calls"].append("warmup")
            kwargs["on_finished"]()

    app = Application()
    monkeypatch.setattr(bootstrap, "get_or_create_qapplication", lambda: app)
    monkeypatch.setattr(bootstrap, "load_main_window_factory", lambda: Window)
    monkeypatch.setattr(bootstrap, "create_startup_splash", lambda *args, **kwargs: types.SimpleNamespace(
        show_message=lambda *args, **kwargs: None,
        close=lambda: None,
        finish=lambda *args: None,
    ))
    monkeypatch.setattr(bootstrap, "validate_license_bootstrap", lambda enabled: types.SimpleNamespace(
        is_valid=state["valid_license"], days_until_expiration=None,
    ))
    monkeypatch.setattr(bootstrap, "show_invalid_license_message", lambda *args: state["calls"].append("license_message"))
    monkeypatch.setattr(bootstrap, "log_and_exit", state["caught"].append)
    monkeypatch.setattr(bootstrap, "_schedule_startup_ui_smoke_exit", lambda app: state["calls"].append("ui_smoke_exit"))
    license_module = types.ModuleType("metroliza.app.license_key_manager")
    license_module.LicenseKeyManager = types.SimpleNamespace(generate_hardware_id=lambda: "synthetic-private-hardware")
    monkeypatch.setitem(sys.modules, license_module.__name__, license_module)
    pdf_module = types.ModuleType("metroliza.parsing.pdf_parser_smoke")
    pdf_module.run_pdf_parser_smoke = lambda *args: state["calls"].append("pdf_smoke")
    monkeypatch.setitem(sys.modules, pdf_module.__name__, pdf_module)

    def records():
        outputs = (
            (home / ".metroliza" / "metroliza.log").read_text(),
            (cwd / "metroliza.log").read_text(), stream.getvalue(),
        )
        assert outputs[0] == outputs[1] == outputs[2]
        return [json.loads(line.split(" ", 2)[2]) for line in outputs[0].splitlines()]

    yield types.SimpleNamespace(
        logger=logger, app=app, window=Window, records=records, state=state,
        pdf_module=pdf_module, setup=setup, stream=stream,
    )
    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _startup_records(trace):
    return [event for event in trace.records() if event["event_code"] == "startup_diagnostic"]


def test_correlated_startup_trace_uses_real_serializer_formatter_and_sinks(startup_trace):
    original_hook = sys.excepthook
    assert bootstrap.run_application() == 0
    events = startup_trace.records()
    assert [event["event_code"] for event in events].count("runtime_provenance") == 1
    assert len(events) == 15
    assert [event["sequence"] for event in events] == list(range(1, 16))
    assert len({event["invocation_id"] for event in events}) == 1
    assert len({event["startup_id"] for event in events}) == 1
    assert events[0]["invocation_id"] != events[0]["startup_id"]
    assert uuid.UUID(hex=events[0]["invocation_id"]).version == 4
    startup = _startup_records(startup_trace)
    assert [event["callsite"] for event in startup] == [
        "bootstrap", "logging_initialize", "logging_ready", "config_load", "config_ready",
        "qapplication_request", "qapplication_ready", "license_check", "main_window_factory",
        "main_window_construct", "main_window_show_request", "main_window_show_returned",
        "event_loop_exec_request", "application_return",
    ]
    assert startup[-2]["outcome"] == "startup_completed"
    assert startup[-2]["exit_code"] is None
    assert startup[-1]["outcome"] == "application_returned"
    assert startup[-1]["exit_code"] == 0
    assert startup_trace.state["calls"] == ["construct", "show", "warmup", "exec"]
    assert sys.excepthook is original_hook
    assert bootstrap._STARTUP_INVOCATION.get() is None


@pytest.mark.parametrize("kind,mode", [
    ("startup", "startup_smoke"), ("pdf", "pdf_smoke"), ("ui", "ui_smoke"),
])
def test_safe_trace_preserves_actual_smoke_routes(startup_trace, monkeypatch, kind, mode):
    if kind == "startup":
        monkeypatch.setenv(bootstrap.STARTUP_SMOKE_ENV, "1")
        # Existing precedence: startup smoke wins even if PDF/UI smoke is also selected.
        monkeypatch.setenv(bootstrap.PDF_PARSER_SMOKE_FIXTURE_ENV, "synthetic-private.pdf")
        monkeypatch.setenv("METROLIZA_STARTUP_UI_SMOKE", "1")
    elif kind == "pdf":
        monkeypatch.setenv(bootstrap.PDF_PARSER_SMOKE_FIXTURE_ENV, "synthetic-private.pdf")
        monkeypatch.setenv(bootstrap.PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV, "synthetic-secret-SQL")
    else:
        monkeypatch.setenv("METROLIZA_STARTUP_UI_SMOKE", "1")
    assert bootstrap.run_application() == 0
    events = _startup_records(startup_trace)
    assert events[-1]["mode"] == mode
    assert len(startup_trace.records()) <= 16
    terminal = [event for event in events if event["outcome"] == "startup_completed"]
    assert len(terminal) == 1
    assert terminal[0]["callsite"] == ("event_loop_exec_request" if kind == "ui" else "smoke_return")
    assert "synthetic-private" not in startup_trace.stream.getvalue()
    assert "synthetic-secret" not in startup_trace.stream.getvalue()
    assert ("exec" in startup_trace.state["calls"]) is (kind == "ui")
    assert ("ui_smoke_exit" in startup_trace.state["calls"]) is (kind == "ui")
    assert ("pdf_smoke" in startup_trace.state["calls"]) is (kind == "pdf")


def test_invalid_license_is_rejection_and_original_return(startup_trace):
    startup_trace.state["valid_license"] = False
    assert bootstrap.run_application() == 1
    events = _startup_records(startup_trace)
    assert events[-2]["callsite"] == "license_rejected"
    assert events[-2]["outcome"] == "startup_rejected"
    assert events[-1]["outcome"] == "application_returned"
    assert events[-1]["exit_code"] == 1
    assert not any(event["outcome"] == "startup_completed" for event in events)
    assert startup_trace.state["calls"] == ["license_message"]
    assert "synthetic-private-hardware" not in startup_trace.stream.getvalue()


@pytest.mark.parametrize("seam,expected_callsite,expected_outcome", [
    ("bootstrap", "bootstrap", "startup_failed"),
    ("logging", "logging_initialize", "startup_failed"),
    ("config", "config_load", "startup_failed"),
    ("qapplication", "qapplication_request", "startup_failed"),
    ("license", "license_check", "startup_failed"),
    ("factory", "main_window_factory", "startup_failed"),
    ("construct", "main_window_construct", "startup_failed"),
    ("show", "main_window_show_request", "startup_failed"),
    ("exec", "event_loop_exec_request", "application_failed"),
])
def test_real_bootstrap_failures_keep_exception_and_boundary(
    startup_trace, monkeypatch, seam, expected_callsite, expected_outcome,
):
    error = RuntimeError("synthetic-path-SQL-document-secret")

    def fail(*args, **kwargs):
        raise error

    attributes = {
        "bootstrap": (bootstrap, "bootstrap_application"),
        "logging": (bootstrap, "ensure_application_logging"),
        "config": (bootstrap, "load_startup_config"),
        "qapplication": (bootstrap, "get_or_create_qapplication"),
        "license": (bootstrap, "validate_license_bootstrap"),
        "factory": (bootstrap, "load_main_window_factory"),
        "construct": (startup_trace.window, "__init__"),
        "show": (startup_trace.window, "show"),
        "exec": (startup_trace.app, "exec"),
    }
    obj, attribute = attributes[seam]
    monkeypatch.setattr(obj, attribute, fail)
    assert bootstrap.run_application() == 1
    assert startup_trace.state["caught"] == [error]
    final = _startup_records(startup_trace)[-1]
    assert final["callsite"] == expected_callsite
    assert final["outcome"] == expected_outcome
    assert final["exception"]["exception_kind"] == "runtime_error"
    assert final["exception"]["has_traceback"] is True
    assert "synthetic-path-SQL-document-secret" not in startup_trace.stream.getvalue()
    assert not any(event["outcome"] == "application_returned" for event in _startup_records(startup_trace))
    assert bootstrap._STARTUP_INVOCATION.get() is None


@pytest.mark.parametrize("exit_code", [7, -9, 2**32-1])
def test_nonzero_application_return_does_not_rewrite_startup(startup_trace, exit_code):
    startup_trace.state["exit_code"] = exit_code
    assert bootstrap.run_application() == exit_code
    events = _startup_records(startup_trace)
    assert events[-2]["outcome"] == "startup_completed"
    assert events[-1]["outcome"] == "application_returned"
    assert events[-1]["exit_code"] == exit_code


@pytest.mark.parametrize("error", [SystemExit(7), KeyboardInterrupt()])
def test_control_flow_base_exceptions_are_not_swallowed(startup_trace, monkeypatch, error):
    def stop(*args):
        raise error
    monkeypatch.setattr(bootstrap, "load_startup_config", stop)
    with pytest.raises(type(error)) as caught:
        bootstrap.run_application()
    assert caught.value is error
    assert not startup_trace.state["caught"]
    assert _startup_records(startup_trace)[-1]["callsite"] == "config_load"
    assert bootstrap._STARTUP_INVOCATION.get() is None


@pytest.mark.parametrize("broken", ["uuid", "constructor", "logger", "formatter", "mode", "clock"])
def test_diagnostic_failures_do_not_change_application_result(startup_trace, monkeypatch, broken):
    from metroliza.shared import logging_utils

    def fail(*args, **kwargs):
        raise OSError("synthetic-diagnostic-secret")
    targets = {
        "uuid": (bootstrap.uuid, "uuid4"),
        "constructor": (bootstrap, "StartupDiagnosticEvent"),
        "logger": (startup_trace.logger, "log"),
        "formatter": (logging_utils.ManagedSafeFormatter, "format"),
        "mode": (bootstrap, "_selected_startup_mode"),
        "clock": (logging_utils.time, "time"),
    }
    monkeypatch.setattr(*targets[broken], fail)
    startup_trace.state["exit_code"] = 7
    assert bootstrap.run_application() == 7
    assert not startup_trace.state["caught"]
    assert "synthetic-diagnostic-secret" not in startup_trace.stream.getvalue()
    assert bootstrap._STARTUP_INVOCATION.get() is None


def test_repeated_and_concurrent_invocations_do_not_mix_ids(startup_trace):
    from concurrent.futures import ThreadPoolExecutor

    assert bootstrap.run_application() == 0
    assert bootstrap.run_application() == 0
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: bootstrap.run_application(), range(2))) == [0, 0]
    grouped = {}
    for event in startup_trace.records():
        grouped.setdefault(event["invocation_id"], []).append(event)
    assert len(grouped) == 4
    for events in grouped.values():
        assert len({event["startup_id"] for event in events}) == 1
        assert [event["sequence"] for event in events] == list(range(1, 16))
        assert events[-1]["outcome"] == "application_returned"
    assert bootstrap._STARTUP_INVOCATION.get() is None


def test_logging_unavailable_does_not_invent_saved_early_history(startup_trace, monkeypatch):
    for handler in tuple(startup_trace.logger.handlers):
        startup_trace.logger.removeHandler(handler)
        handler.close()
    error = OSError("synthetic-unavailable-secret")
    def fail():
        raise error
    monkeypatch.setattr(bootstrap, "ensure_application_logging", fail)
    assert bootstrap.run_application() == 1
    assert startup_trace.state["caught"] == [error]
    assert startup_trace.records() == []


def test_nested_invocation_restores_outer_context(startup_trace, monkeypatch):
    original = bootstrap.load_startup_config
    nested = False
    def load_config():
        nonlocal nested
        if not nested:
            nested = True
            assert bootstrap.run_application() == 0
        return original()
    monkeypatch.setattr(bootstrap, "load_startup_config", load_config)
    assert bootstrap.run_application() == 0
    groups = {}
    for event in startup_trace.records():
        groups.setdefault(event["invocation_id"], []).append(event)
    assert len(groups) == 2
    assert all([event["sequence"] for event in events] == list(range(1, 16)) for events in groups.values())
    assert bootstrap._STARTUP_INVOCATION.get() is None


def test_lightweight_diagnostic_imports_create_no_files_or_optional_runtime(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; import metroliza.shared.diagnostic_events; "
            "import metroliza.shared.logging_utils; "
            "assert not any(name.split('.')[0] in "
            "{'PyQt6','onnxruntime','rapidocr','cv2','pandas'} for name in sys.modules)"
        )],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["startup", "pdf"])
def test_smoke_errors_and_nonzero_returns_are_not_startup_success(startup_trace, monkeypatch, mode):
    if mode == "startup":
        monkeypatch.setenv(bootstrap.STARTUP_SMOKE_ENV, "1")
        helper = "run_startup_smoke_mode"
    else:
        monkeypatch.setenv(bootstrap.PDF_PARSER_SMOKE_FIXTURE_ENV, "synthetic-private.pdf")
        helper = "run_pdf_parser_smoke_mode"
    monkeypatch.setattr(bootstrap, helper, lambda *args: 9)
    assert bootstrap.run_application() == 9
    events = _startup_records(startup_trace)
    assert events[-2]["outcome"] == "startup_rejected"
    assert events[-2]["callsite"] == "smoke_return"
    assert events[-1]["exit_code"] == 9
    error = ValueError("synthetic-secret-document")
    def fail(*args):
        raise error
    monkeypatch.setattr(bootstrap, helper, fail)
    assert bootstrap.run_application() == 1
    assert startup_trace.state["caught"] == [error]
    final = _startup_records(startup_trace)[-1]
    assert final["outcome"] == "startup_failed"
    assert final["callsite"] == "smoke_work"
    assert final["exception"]["exception_kind"] == "value_error"
    assert not any(event["outcome"] == "startup_completed" for event in _startup_records(startup_trace))


def test_original_error_survives_failure_of_correlated_error_emission(startup_trace, monkeypatch):
    error = ValueError("synthetic-operation-secret")
    def fail_config():
        raise error
    def fail_sink(*args, **kwargs):
        raise OSError("synthetic-emitter-secret")
    monkeypatch.setattr(bootstrap, "load_startup_config", fail_config)
    monkeypatch.setattr(startup_trace.logger, "log", fail_sink)
    assert bootstrap.run_application() == 1
    assert startup_trace.state["caught"] == [error]
    assert "synthetic-" not in startup_trace.stream.getvalue()
    assert bootstrap._STARTUP_INVOCATION.get() is None


@pytest.mark.parametrize("returned", [True, 2**100, object()])
def test_unrepresentable_return_preserves_original_without_coercion(startup_trace, returned):
    startup_trace.state["exit_code"] = returned
    assert bootstrap.run_application() is returned
    assert _startup_records(startup_trace)[-1]["callsite"] == "event_loop_exec_request"
    assert not startup_trace.state["caught"]
