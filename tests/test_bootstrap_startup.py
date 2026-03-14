import unittest
import types
from unittest.mock import patch

import metroliza
from modules.license_bootstrap import validate_license_bootstrap


class TestBootstrapStartup(unittest.TestCase):
    def test_load_startup_config_defaults_to_license_verification_disabled(self):
        with patch.dict("os.environ", {}, clear=True):
            config = metroliza.load_startup_config()

        self.assertFalse(config.startup_smoke_mode)
        self.assertFalse(config.license_verification_enabled)

    def test_load_startup_config_can_disable_license_verification(self):
        with patch.dict(
            "os.environ",
            {
                metroliza.LICENSE_MODE_ENV: "false",
                metroliza.STARTUP_SMOKE_ENV: "0",
            },
            clear=True,
        ):
            config = metroliza.load_startup_config()

        self.assertFalse(config.license_verification_enabled)

    def test_validate_license_bootstrap_skips_validation_when_disabled(self):
        with patch("modules.license_bootstrap.verify_license") as verify_mock:
            result = validate_license_bootstrap(False)

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.days_until_expiration)
        verify_mock.assert_not_called()

    def test_validate_license_bootstrap_invalid_key_when_enabled(self):
        with patch("modules.license_bootstrap.verify_license", return_value=False):
            result = validate_license_bootstrap(True)

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.days_until_expiration)

    def test_validate_license_bootstrap_valid_enabled_returns_expiration_days(self):
        fake_manager = types.SimpleNamespace(read_license_key_file=lambda: "license-token")
        fake_module = types.SimpleNamespace(LicenseKeyManager=fake_manager)

        with patch("modules.license_bootstrap.verify_license", return_value=True), patch(
            "modules.license_bootstrap.get_days_until_expiration", return_value=12
        ), patch.dict("sys.modules", {"modules.license_key_manager": fake_module}):
            result = validate_license_bootstrap(True)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.days_until_expiration, 12)

    def test_bootstrap_application_uses_smoke_mode_when_enabled(self):
        smoke_config = metroliza.StartupConfig(startup_smoke_mode=True, license_verification_enabled=True)
        with patch("metroliza.initialize_logging") as init_logging, patch(
            "metroliza.load_startup_config", return_value=smoke_config
        ), patch("metroliza.run_startup_smoke_mode", return_value=0) as smoke_mode, patch(
            "metroliza.launch_ui"
        ) as launch_ui:
            result = metroliza.bootstrap_application()

        self.assertEqual(result, 0)
        smoke_mode.assert_called_once_with(init_logging.return_value)
        launch_ui.assert_not_called()

    def test_run_application_logs_and_returns_error_on_startup_exception(self):
        error = RuntimeError("startup failure")
        with patch("metroliza.bootstrap_application", side_effect=error), patch("metroliza.log_and_exit") as log_and_exit:
            result = metroliza.run_application()

        self.assertEqual(result, 1)
        log_and_exit.assert_called_once_with(error)


if __name__ == "__main__":
    unittest.main()
