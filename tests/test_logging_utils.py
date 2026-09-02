import io
import logging
import logging.handlers
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from modules.logging_utils import (
    LoggingConfig,
    RedactingFormatter,
    ensure_application_logging,
    redact_log_text,
    resolve_logging_config,
)


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

    def test_ensure_application_logging_falls_back_when_standard_log_paths_are_unwritable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home_file"
            fake_home.write_text("not a directory", encoding="utf-8")
            fake_cwd = root / "cwd_file"
            fake_cwd.write_text("not a directory", encoding="utf-8")
            fallback_root = root / "runtime"

            logger = logging.getLogger("metroliza_test_logging_fallback")
            self._reset_logger(logger)
            logger.setLevel(logging.NOTSET)
            logger.propagate = False

            try:
                with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                    "modules.logging_utils.Path.home", return_value=fake_home
                ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd), patch(
                    "modules.logging_utils.tempfile.gettempdir", return_value=str(fallback_root)
                ):
                    ensure_application_logging(level=logging.ERROR)
                    logger.error("startup log path fallback worked")

                fallback_log = fallback_root / "metroliza" / "metroliza.log"
                file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]

                self.assertEqual(len(file_handlers), 1)
                self.assertTrue(fallback_log.exists())
                self.assertIn("startup log path fallback worked", fallback_log.read_text(encoding="utf-8"))
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

    def test_managed_file_and_console_outputs_redact_final_exception_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            console = io.StringIO()
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(5)]

            logger = logging.getLogger("metroliza_test_managed_redaction")
            self._reset_logger(logger)
            logger.propagate = False
            config = LoggingConfig(logging.DEBUG, logging.DEBUG, logging.DEBUG)

            try:
                with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                    "modules.logging_utils.Path.home", return_value=fake_home
                ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd), patch(
                    "sys.stderr", console
                ):
                    ensure_application_logging(config=config)
                    logger.error("password=%s", markers[0])
                    try:
                        try:
                            raise ValueError(f"token={markers[1]}")
                        except ValueError as inner:
                            inner.add_note(f"source={markers[2]}")
                            raise RuntimeError(markers[3]) from inner
                    except RuntimeError as chained:
                        group = ExceptionGroup(markers[4], [chained, KeyError(markers[4])])
                        logger.error(
                            "safe exception context",
                            exc_info=(type(group), group, group.__traceback__),
                        )

                    record = logger.makeRecord(
                        logger.name,
                        logging.ERROR,
                        __file__,
                        1,
                        "safe cached-field context",
                        (),
                        None,
                    )
                    record.exc_text = f"credential={markers[2]}"
                    record.stack_info = f"path={markers[3]}"
                    logger.handle(record)
                    logger.info("ordinary safe diagnostic remains readable")

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                for output in (home_log, console.getvalue()):
                    self.assertTrue(all(marker not in output for marker in markers))
                    self.assertIn("[REDACTED]", output)
                    self.assertIn("ExceptionGroup", output)
                    self.assertIn("RuntimeError", output)
                    self.assertIn("ValueError", output)
                    self.assertIn("KeyError", output)
                    self.assertIn("chain=present", output)
                    self.assertIn("group=present", output)
                    self.assertIn("traceback=present", output)
                    self.assertIn("notes=present", output)
                    self.assertIn("cached_exception_text=present", output)
                    self.assertIn("stack_info=present", output)
                    self.assertIn("ordinary safe diagnostic remains readable", output)
            finally:
                self._reset_logger(logger)

    def test_redaction_is_limited_to_explicit_reviewable_classes(self):
        marker = f"generated-{uuid.uuid4().hex}"
        sensitive = (
            f"password={marker}",
            f'{{"password": "{marker}"}}',
            f"passphrase: {marker}",
            f"token={marker}",
            f"access_token={marker}",
            f"refresh-token={marker}",
            f"api key={marker}",
            f"private_key={marker}",
            f"secret-key={marker}",
            f"credential={marker}",
            f"Authorization: Bearer {marker}",
            f"Bearer {marker}",
            f"postgresql://generated:{marker}@localhost/db",
            f"https://localhost/path?token={marker}&page=1",
            f"dsn=Server=localhost;Password={marker}",
            f"connection_string=Server=localhost;Token={marker}",
            f"sql=SELECT value FROM generated WHERE value='{marker}'",
            f"query=SELECT '{marker}'",
            f"source=return '{marker}'",
            f"path=/generated/{marker}",
        )
        for value in sensitive:
            with self.subTest(value=value[:40]):
                output = redact_log_text(value)
                self.assertNotIn(marker, output)
                self.assertIn("[REDACTED]", output)

        safe = (
            "tokenizer=wordpiece status=ok",
            "passwordless authentication enabled",
            "query completed successfully",
            "ordinary safe diagnostic remains readable",
        )
        for value in safe:
            with self.subTest(value=value):
                self.assertEqual(redact_log_text(value), value)

    def test_formatter_handles_percent_mappings_objects_and_broken_str(self):
        stream = io.StringIO()
        marker = f"generated-{uuid.uuid4().hex}"

        class SensitiveObject:
            def __str__(self):
                return f"token={marker}"

        class BrokenObject:
            def __str__(self):
                raise RuntimeError(marker)

        logger = logging.getLogger("metroliza_test_format_arguments")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            logger.error("password=%s", marker)
            logger.error("%(credential)s", {"credential": marker})
            logger.error("object=%s", SensitiveObject())
            logger.error("exception=%s", RuntimeError(marker))
            logger.error("broken=%s", BrokenObject())
            logger.info("safe count=%d", 3)
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertNotIn(marker, output)
        self.assertIn("[REDACTED]", output)
        self.assertIn("RuntimeError", output)
        self.assertIn("log_message=[unformattable]", output)
        self.assertIn("safe count=3", output)

    def test_formatter_does_not_mutate_record_seen_by_other_handlers(self):
        marker = f"generated-{uuid.uuid4().hex}"
        exception = RuntimeError(marker)
        arguments = (marker,)
        exc_info = (type(exception), exception, exception.__traceback__)
        record = logging.LogRecord(
            "metroliza_test_record_isolation",
            logging.ERROR,
            __file__,
            1,
            "password=%s",
            arguments,
            exc_info,
        )
        record.exc_text = f"token={marker}"
        record.stack_info = f"source={marker}"

        output = RedactingFormatter("%(message)s").format(record)

        self.assertNotIn(marker, output)
        self.assertEqual(record.msg, "password=%s")
        self.assertEqual(record.args, arguments)
        self.assertIs(record.exc_info, exc_info)
        self.assertEqual(record.exc_text, f"token={marker}")
        self.assertEqual(record.stack_info, f"source={marker}")

    def test_formatter_bounds_output_and_survives_hostile_exception_name(self):
        marker = f"generated-{uuid.uuid4().hex}"

        class HostileName(str):
            def __format__(self, _format_spec):
                return marker

        class GeneratedError(RuntimeError):
            pass

        GeneratedError.__name__ = HostileName("GeneratedError")
        record = logging.LogRecord(
            "metroliza_test_bounded_output",
            logging.ERROR,
            __file__,
            1,
            "safe %s",
            ("x" * 100_000,),
            (GeneratedError, GeneratedError(marker), None),
        )

        output = RedactingFormatter("%(message)s").format(record)

        self.assertNotIn(marker, output)
        self.assertIn("exception_types=Exception", output)
        self.assertIn("[truncated]", output)
        self.assertLessEqual(len(output), 16_500)

    def test_repeated_setup_reuses_handlers_and_one_redacting_formatter_layer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            logger = logging.getLogger("metroliza_test_redaction_idempotence")
            self._reset_logger(logger)
            logger.propagate = False
            config = LoggingConfig(logging.INFO, logging.INFO, logging.INFO)

            try:
                with patch("modules.logging_utils.logging.getLogger", return_value=logger), patch(
                    "modules.logging_utils.Path.home", return_value=fake_home
                ), patch("modules.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(config=config)
                    first_handlers = tuple(logger.handlers)
                    ensure_application_logging(config=config)

                self.assertEqual(tuple(logger.handlers), first_handlers)
                self.assertEqual(len(first_handlers), 3)
                self.assertTrue(
                    all(type(handler.formatter) is RedactingFormatter for handler in first_handlers)
                )
            finally:
                self._reset_logger(logger)


if __name__ == "__main__":
    unittest.main()
