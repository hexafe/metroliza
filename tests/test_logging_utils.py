import logging
import logging.handlers
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.logging_utils import ensure_application_logging, resolve_logging_config


class TestLoggingUtils(unittest.TestCase):
    def _reset_logger(self, logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_ensure_application_logging_writes_to_home_and_cwd_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging")
            self._reset_logger(logger)
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            try:
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
            finally:
                self._reset_logger(logger)

    def test_ensure_application_logging_uses_rotating_file_handlers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging_rotating")
            self._reset_logger(logger)
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            try:
                with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                    "modules.logging_utils.Path.home", return_value=fake_home
                ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)

                file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
                self.assertEqual(len(file_handlers), 2)
                self.assertTrue(all(isinstance(h, logging.handlers.RotatingFileHandler) for h in file_handlers))
                self.assertTrue(all(h.maxBytes == 10 * 1024 * 1024 for h in file_handlers))
                self.assertTrue(all(h.backupCount == 7 for h in file_handlers))
            finally:
                self._reset_logger(logger)

    def test_ensure_application_logging_replaces_non_rotating_file_handlers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging_replace")
            self._reset_logger(logger)
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            (fake_home / ".metroliza").mkdir(parents=True, exist_ok=True)
            legacy_home_handler = logging.FileHandler(str(fake_home / ".metroliza" / "metroliza.log"), encoding="utf-8")
            legacy_cwd_handler = logging.FileHandler(str(fake_cwd / "metroliza.log"), encoding="utf-8")
            logger.addHandler(legacy_home_handler)
            logger.addHandler(legacy_cwd_handler)

            try:
                with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                    "modules.logging_utils.Path.home", return_value=fake_home
                ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)

                file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
                self.assertEqual(len(file_handlers), 2)
                self.assertTrue(all(isinstance(h, logging.handlers.RotatingFileHandler) for h in file_handlers))
                self.assertTrue(all(h.maxBytes == 10 * 1024 * 1024 for h in file_handlers))
                self.assertTrue(all(h.backupCount == 7 for h in file_handlers))
            finally:
                self._reset_logger(logger)

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
            self._reset_logger(logger)
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            env = {
                "METROLIZA_LOG_LEVEL": "INFO",
                "METROLIZA_FILE_LOG_LEVEL": "ERROR",
                "METROLIZA_CONSOLE_LOG_LEVEL": "WARNING",
                "METROLIZA_SUPPORT_BUILD": "0",
            }
            try:
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

                file_handlers = [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
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

                self.assertTrue(all(h.maxBytes == 10 * 1024 * 1024 for h in file_handlers))
                self.assertTrue(all(h.backupCount == 7 for h in file_handlers))
                self.assertTrue(all(h.formatter._fmt == '%(asctime)s %(levelname)s [%(name)s] [%(threadName)s] %(message)s' for h in file_handlers))
                self.assertEqual(console_handlers[0].formatter._fmt, '%(asctime)s %(levelname)s [%(name)s] [%(threadName)s] %(message)s')
                self.assertEqual(console_handlers[0].level, logging.WARNING)
            finally:
                self._reset_logger(logger)

    def test_default_logging_levels_capture_info_and_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging_defaults")
            self._reset_logger(logger)
            logger.propagate = False

            env = {
                "METROLIZA_LOG_LEVEL": "",
                "METROLIZA_FILE_LOG_LEVEL": "",
                "METROLIZA_CONSOLE_LOG_LEVEL": "",
                "METROLIZA_SUPPORT_BUILD": "0",
            }
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "modules.logging_utils.logging.getLogger", return_value=logger
                ), patch("modules.logging_utils.Path.home", return_value=fake_home), patch(
                    "modules.logging_utils.Path.cwd", return_value=fake_cwd
                ):
                    config = ensure_application_logging()
                    logger.debug("debug message should be filtered")
                    logger.info("info message should be logged")
                    logger.warning("warning message should be logged")

                self.assertEqual(config.global_level, logging.INFO)
                self.assertEqual(config.file_level, logging.INFO)
                self.assertIsNone(config.console_level)

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(encoding="utf-8")
                cwd_log = (fake_cwd / "metroliza.log").read_text(encoding="utf-8")
                for content in (home_log, cwd_log):
                    self.assertNotIn("debug message should be filtered", content)
                    self.assertIn("info message should be logged", content)
                    self.assertIn("warning message should be logged", content)
            finally:
                self._reset_logger(logger)

    def test_formatter_includes_logger_and_thread_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging_metadata")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                    "modules.logging_utils.Path.home", return_value=fake_home
                ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("metadata check")

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(encoding="utf-8")
                self.assertIn("[metroliza_test_logging_metadata]", home_log)
                self.assertIn(f"[{threading.current_thread().name}]", home_log)
            finally:
                self._reset_logger(logger)


if __name__ == "__main__":
    unittest.main()
