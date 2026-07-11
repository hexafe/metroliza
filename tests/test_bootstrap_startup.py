import os
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
