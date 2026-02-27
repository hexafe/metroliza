import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.logging_utils import ensure_application_logging, resolve_logging_config


class TestLoggingUtils(unittest.TestCase):
    def test_ensure_application_logging_writes_to_home_and_cwd_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging")
            logger.handlers = []
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                "modules.logging_utils.Path.home", return_value=fake_home
            ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd):
                ensure_application_logging(level=logging.ERROR)
                logger.error("google drive export failed")

            home_log = fake_home / ".metroliza" / "metroliza.log"
            cwd_log = fake_cwd / "metroliza.log"

            self.assertTrue(home_log.exists())
            self.assertTrue(cwd_log.exists())
            self.assertIn("google drive export failed", home_log.read_text())
            self.assertIn("google drive export failed", cwd_log.read_text())

    def test_resolve_logging_config_support_build_defaults_to_debug(self):
        with patch.dict(
            "os.environ",
            {
                "METROLIZA_SUPPORT_BUILD": "1",
                "METROLIZA_LOG_LEVEL": "",
                "METROLIZA_FILE_LOG_LEVEL": "",
                "METROLIZA_CONSOLE_LOG_LEVEL": "",
            },
            clear=False,
        ):
            config = resolve_logging_config()

        self.assertEqual(config.global_level, logging.DEBUG)
        self.assertEqual(config.file_level, logging.DEBUG)
        self.assertIsNone(config.console_level)

    def test_ensure_application_logging_configures_independent_handler_levels(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging_levels")
            logger.handlers = []
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            env = {
                "METROLIZA_LOG_LEVEL": "INFO",
                "METROLIZA_FILE_LOG_LEVEL": "ERROR",
                "METROLIZA_CONSOLE_LOG_LEVEL": "WARNING",
                "METROLIZA_SUPPORT_BUILD": "0",
            }
            with patch.dict("os.environ", env, clear=False), patch(
                "modules.logging_utils.logging.getLogger", return_value=logger
            ), patch("modules.logging_utils.Path.home", return_value=fake_home), patch(
                "modules.logging_utils.Path.cwd", return_value=fake_cwd
            ):
                config = ensure_application_logging()

            self.assertEqual(config.global_level, logging.INFO)
            self.assertEqual(config.file_level, logging.ERROR)
            self.assertEqual(config.console_level, logging.WARNING)
            self.assertEqual(logger.level, logging.INFO)

            file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
            console_handlers = [
                h
                for h in logger.handlers
                if isinstance(h, logging.StreamHandler)
                and not isinstance(h, logging.FileHandler)
                and getattr(h, "_metroliza_console_handler", False)
            ]
            self.assertEqual(len(file_handlers), 2)
            self.assertEqual(len(console_handlers), 1)
            self.assertTrue(all(h.level == logging.ERROR for h in file_handlers))
            self.assertEqual(console_handlers[0].level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
