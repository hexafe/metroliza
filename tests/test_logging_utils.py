import io
import logging
import logging.handlers
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from metroliza.shared import logging_utils as logging_utils_module
from metroliza.shared.logging_utils import (
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ):
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ):
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch(
                    "metroliza.shared.logging_utils.tempfile.gettempdir",
                    return_value=str(fallback_root),
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ):
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
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
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
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ):
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch(
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

    def test_r3_quoted_authorization_labels_are_redacted_in_final_output(self):
        stream = io.StringIO()
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(6)]
        logger = logging.getLogger("metroliza_test_quoted_authorization")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            logger.error("{'Authorization': 'Basic %s', 'status': 'ready'}", markers[0])
            logger.error('{"Authorization": "Basic %s", "state": "safe"}', markers[1])
            logger.error("{'Proxy-Authorization': Basic %s, 'mode': 'safe'}", markers[2])
            logger.error('{"Proxy-Authorization": Bearer %s, "kind": "safe"}', markers[3])
            logger.error("{'Authorization': 'Basic %s, 'result': 'safe'}", markers[4])
            logger.error(
                '{"Proxy-Authorization": "Basic %s; outcome=safe',
                markers[5],
            )
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertFalse(
            any(marker in output for marker in markers),
            "quoted authorization credential reached formatted output",
        )
        self.assertIn("Authorization", output)
        self.assertIn("Proxy-Authorization", output)
        for intentionally_discarded_tail in (
            "status",
            "state",
            "mode",
            "kind",
            "result",
            "outcome",
        ):
            self.assertNotIn(intentionally_discarded_tail, output)
        self.assertGreaterEqual(output.count("[REDACTED]"), len(markers))

    def test_r4_authorization_fields_fail_closed_through_rendered_record_tail(self):
        formatter = RedactingFormatter("%(levelname)s %(message)s")
        cases = (
            (
                "safe-prefix {'Authorization': ['Basic {marker}', 'alternate']} trailing-list",
                "ERROR safe-prefix {'Authorization': [REDACTED]",
            ),
            (
                'safe-prefix {"Authorization": ["Basic {marker}", "alternate"]} trailing-json',
                'ERROR safe-prefix {"Authorization": [REDACTED]',
            ),
            (
                "safe-prefix Authorization = ('Bearer {marker}', 'alternate') trailing-tuple",
                "ERROR safe-prefix Authorization = [REDACTED]",
            ),
            (
                "safe-prefix {'Proxy-Authorization': "
                "{'nested': {'credential': 'Bearer {marker}'}}} trailing-mapping",
                "ERROR safe-prefix {'Proxy-Authorization': [REDACTED]",
            ),
            (
                "safe-prefix PROXY_AUTHORIZATION: {'value': 'Basic {marker}'} trailing-underscore",
                "ERROR safe-prefix PROXY_AUTHORIZATION: [REDACTED]",
            ),
            (
                "safe-prefix Authorization: [Basic {marker}\ntrailing-multiline",
                "ERROR safe-prefix Authorization: [REDACTED]",
            ),
            (
                "safe-prefix Authorization: ]}}Basic {marker} trailing-malformed",
                "ERROR safe-prefix Authorization: [REDACTED]",
            ),
            (
                r'safe-prefix {\"Authorization\": [\"Basic {marker}\"]} trailing-escaped',
                r'ERROR safe-prefix {\"Authorization\": [REDACTED]',
            ),
        )

        for template, expected in cases:
            marker = f"generated-{uuid.uuid4().hex}"
            message = template.replace("{marker}", marker)
            record = logging.LogRecord(
                "metroliza_test_r4_authorization_tail",
                logging.ERROR,
                __file__,
                1,
                message,
                (),
                None,
            )

            with self.subTest(shape=template[:48]):
                output = formatter.format(record)
                self.assertEqual(output, expected)
                self.assertNotIn(marker, output)
                self.assertNotIn("trailing-", output)

    def test_r5_existing_redaction_marker_does_not_preserve_untrusted_tail(self):
        marker = f"generated-{uuid.uuid4().hex}"
        formatter = RedactingFormatter("%(message)s")
        message = (
            "safe-prefix Authorization: [REDACTED]; retained-structure; "
            f"Proxy Authorization = ('Basic {marker}',) intentionally-discarded"
        )
        record = logging.LogRecord(
            "metroliza_test_r4_authorization_idempotence",
            logging.ERROR,
            __file__,
            1,
            message,
            (),
            None,
        )

        output = formatter.format(record)
        repeated_record = logging.LogRecord(
            "metroliza_test_r4_authorization_idempotence_repeat",
            logging.ERROR,
            __file__,
            1,
            output,
            (),
            None,
        )

        self.assertEqual(formatter.format(repeated_record), output)
        self.assertEqual(output, "safe-prefix Authorization: [REDACTED]")
        self.assertNotIn(marker, output)
        self.assertNotIn("retained-structure", output)
        self.assertNotIn("intentionally-discarded", output)

    def test_r5_terminal_secret_label_variants_contract_the_rendered_tail(self):
        formatter = RedactingFormatter("%(levelname)s %(message)s")
        assignments = (
            ("client_secret", ": "),
            ("client-secret", " = "),
            ("client secret", ":"),
            ("secret", "="),
        )

        for label, separator in assignments:
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(2)]
            message = f"safe-prefix {label}{separator}{markers[0]}\nuntrusted-tail={markers[1]}"
            record = logging.LogRecord(
                "metroliza_test_r5_terminal_secret_labels",
                logging.ERROR,
                __file__,
                1,
                message,
                (),
                None,
            )

            with self.subTest(label=label, separator=separator):
                output = formatter.format(record)
                self.assertEqual(
                    output,
                    f"ERROR safe-prefix {label}{separator}[REDACTED]",
                )
                self.assertTrue(all(marker not in output for marker in markers))

    def test_r5_secret_label_variants_redact_top_level_and_nested_mapping_keys(self):
        formatter = RedactingFormatter("%(message)s")
        keys = ("client_secret", "client-secret", "client secret", "secret")

        for key in keys:
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(2)]
            top_level = logging.LogRecord(
                "metroliza_test_r5_top_level_secret_keys",
                logging.ERROR,
                __file__,
                1,
                f"%({key})s",
                ({key: markers[0]},),
                None,
            )
            nested = logging.LogRecord(
                "metroliza_test_r5_nested_secret_keys",
                logging.ERROR,
                __file__,
                1,
                "payload=%s",
                ({"safe": "kept", "nested": {key: markers[1]}},),
                None,
            )

            with self.subTest(key=key):
                outputs = (formatter.format(top_level), formatter.format(nested))
                self.assertTrue(
                    all(marker not in output for marker in markers for output in outputs)
                )
                self.assertTrue(all("[REDACTED]" in output for output in outputs))

    def test_r5_multiline_structured_fields_contract_through_end_of_record(self):
        formatter = RedactingFormatter("%(levelname)s %(message)s")
        assignments = (
            ("sql", ": "),
            ("query", "="),
            ("source", " :"),
            ("path", " = "),
            ("dsn", ":"),
            ("connection_string", "="),
        )

        for label, separator in assignments:
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(2)]
            record = logging.LogRecord(
                "metroliza_test_r5_multiline_terminal_fields",
                logging.ERROR,
                __file__,
                1,
                (
                    f"safe-prefix {label}{separator}{markers[0]}\n"
                    f"second-sensitive-line {markers[1]}\nfinal-diagnostic"
                ),
                (),
                None,
            )

            with self.subTest(label=label, separator=separator):
                output = formatter.format(record)
                self.assertEqual(
                    output,
                    f"ERROR safe-prefix {label}{separator}[REDACTED]",
                )
                self.assertTrue(all(marker not in output for marker in markers))
                self.assertNotIn("final-diagnostic", output)

    def test_r5_authorization_sentinels_do_not_hide_appended_credentials(self):
        formatter = RedactingFormatter("%(message)s")
        labels = ("Authorization", "Proxy-Authorization")

        for label in labels:
            marker = f"generated-{uuid.uuid4().hex}"
            record = logging.LogRecord(
                "metroliza_test_r5_appended_authorization",
                logging.ERROR,
                __file__,
                1,
                f"safe-prefix {label}: [REDACTED], Basic {marker}",
                (),
                None,
            )

            with self.subTest(label=label):
                output = formatter.format(record)
                self.assertEqual(output, f"safe-prefix {label}: [REDACTED]")
                self.assertNotIn(marker, output)

    def test_r5_terminal_field_keeps_only_generated_exception_structure(self):
        marker = f"generated-{uuid.uuid4().hex}"
        try:
            try:
                cause = ValueError(marker)
                cause.add_note(marker)
                raise cause
            except ValueError as cause:
                raise ExceptionGroup(marker, [RuntimeError(marker)]) from cause
        except ExceptionGroup as exception:
            record = logging.LogRecord(
                "metroliza_test_r5_terminal_field_structural_suffix",
                logging.ERROR,
                __file__,
                1,
                f"safe-prefix client_secret={marker}\nuntrusted-tail={marker}",
                (),
                (type(exception), exception, exception.__traceback__),
            )

        output = RedactingFormatter("%(message)s").format(record)

        self.assertTrue(output.startswith("safe-prefix client_secret=[REDACTED] ["))
        self.assertNotIn(marker, output)
        for generated_diagnostic in (
            "exception_types=ExceptionGroup,RuntimeError,ValueError",
            "chain=present",
            "group=present",
            "traceback=present",
            "notes=present",
        ):
            self.assertIn(generated_diagnostic, output)

    def test_r5_unassigned_sensitive_words_remain_unchanged(self):
        messages = (
            "secret rotation completed",
            "query completed",
            "authorization failed",
            "path lookup succeeded",
        )
        formatter = RedactingFormatter("%(message)s")

        for message in messages:
            record = logging.LogRecord(
                "metroliza_test_r5_safe_unassigned_prose",
                logging.INFO,
                __file__,
                1,
                message,
                (),
                None,
            )
            with self.subTest(message=message):
                self.assertEqual(formatter.format(record), message)

    def test_r4_already_redacted_authorization_preserves_structural_suffix(self):
        marker = f"generated-{uuid.uuid4().hex}"
        exception = RuntimeError(marker)
        record = logging.LogRecord(
            "metroliza_test_r4_authorization_structural_suffix",
            logging.ERROR,
            __file__,
            1,
            "safe-prefix Authorization: [REDACTED]",
            (),
            (type(exception), exception, exception.__traceback__),
        )

        output = RedactingFormatter("%(message)s").format(record)

        self.assertTrue(output.startswith("safe-prefix Authorization: [REDACTED] ["))
        self.assertIn("exception_types=RuntimeError", output)
        self.assertIn("chain=absent", output)
        self.assertNotIn(marker, output)

    def test_r4_unassigned_authorization_prose_remains_unchanged(self):
        messages = (
            "authorization failed",
            "proxy authorization unavailable",
            "AuthorizationHandler failed safely",
        )
        formatter = RedactingFormatter("%(message)s")

        for message in messages:
            record = logging.LogRecord(
                "metroliza_test_r4_safe_authorization_prose",
                logging.INFO,
                __file__,
                1,
                message,
                (),
                None,
            )
            with self.subTest(message=message):
                self.assertEqual(formatter.format(record), message)

    def test_r3_nested_exception_arguments_are_sanitized_recursively(self):
        stream = io.StringIO()
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(5)]
        logger = logging.getLogger("metroliza_test_nested_exception_arguments")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            logger.error("list=%s", [ValueError(markers[0]), "safe-list"])
            logger.error("tuple=%s", ("safe-tuple", KeyError(markers[1])))
            logger.error(
                "mapping=%s",
                {
                    "outer": {"error": RuntimeError(markers[2]), "token": markers[3]},
                    "safe": 7,
                },
            )
            logger.error(
                "mixed=%s",
                [{"safe": ("kept", OSError(markers[4]))}],
            )
            logger.info("ordinary count=%d label=%s", 3, "ready")
            logger.info(
                "percent name=%(name)s count=%(count)d",
                {"name": "safe-name", "count": 4},
            )
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertFalse(
            any(marker in output for marker in markers),
            "nested exception or sensitive mapping value reached formatted output",
        )
        for exception_type in ("ValueError", "KeyError", "RuntimeError", "OSError"):
            self.assertIn(exception_type, output)
        for safe_text in (
            "safe-list",
            "safe-tuple",
            "kept",
            "ordinary count=3 label=ready",
            "percent name=safe-name count=4",
        ):
            self.assertIn(safe_text, output)
        self.assertNotIn("'safe': 7", output)
        self.assertIn("[REDACTED]", output)

    def test_r3_nested_argument_cycles_hostility_and_budget_fail_closed(self):
        stream = io.StringIO()
        marker = f"generated-{uuid.uuid4().hex}"

        class HostileMapping(dict):
            def items(self):
                raise RuntimeError(marker)

        cyclic: list[object] = ["safe-cycle"]
        cyclic.append(cyclic)
        over_budget = list(range(1_024))
        hostile = [HostileMapping({"safe": "value"})]

        logger = logging.getLogger("metroliza_test_bounded_nested_arguments")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            logger.error("cycle=%s", cyclic)
            logger.error("budget=%s", over_budget)
            logger.error("hostile=%s", hostile)
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertNotIn(marker, output)
        self.assertGreaterEqual(
            output.count("[unsafe log arguments]"),
            3,
            "cycle, hostile mapping, or node budget did not fail closed",
        )

    def test_r3_container_messages_are_sanitized_recursively(self):
        stream = io.StringIO()
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(3)]
        logger = logging.getLogger("metroliza_test_container_messages")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            logger.error([ValueError(markers[0]), "safe-list-message"])
            logger.error(("safe-tuple-message", KeyError(markers[1])))
            logger.error(
                {"safe": "kept-message", "nested": [RuntimeError(markers[2])]},
            )
            logger.info("ordinary scalar message remains readable")
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertFalse(
            any(marker in output for marker in markers),
            "an exception nested in a direct container message reached formatted output",
        )
        for exception_type in ("ValueError", "KeyError", "RuntimeError"):
            self.assertIn(exception_type, output)
        for safe_text in (
            "safe-list-message",
            "safe-tuple-message",
            "kept-message",
            "ordinary scalar message remains readable",
        ):
            self.assertIn(safe_text, output)

    def test_r3_sensitive_str_subclass_mapping_keys_are_redacted(self):
        stream = io.StringIO()
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(3)]

        class HostileSensitiveKey(str):
            def __str__(self):
                return "ordinary"

            def strip(self, _chars=None):
                return "ordinary"

            def casefold(self):
                return "ordinary"

        logger = logging.getLogger("metroliza_test_str_subclass_mapping_keys")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            for key, marker in zip(("token", "credential", "authorization"), markers):
                logger.error(f"%({key})s", {HostileSensitiveKey(key): marker})
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertFalse(
            any(marker in output for marker in markers),
            "a sensitive str-subclass mapping key bypassed value redaction",
        )
        self.assertEqual(output.count("[REDACTED]"), len(markers))

    def test_r3_direct_mapping_message_normalizes_hostile_str_subclass_keys(self):
        stream = io.StringIO()
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(2)]

        class HostileSensitiveKey(str):
            def __repr__(self):
                return markers[0]

            def __str__(self):
                return "ordinary"

            def strip(self, _chars=None):
                return "ordinary"

            def casefold(self):
                return "ordinary"

        logger = logging.getLogger("metroliza_test_hostile_mapping_key_repr")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            logger.error(
                {HostileSensitiveKey("token"): markers[1], "safe": "kept-message"},
            )
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertFalse(
            any(marker in output for marker in markers),
            "a hostile str-subclass mapping key repr reached formatted output",
        )
        self.assertIn("'token': [REDACTED]", output)
        self.assertNotIn("kept-message", output)

    def test_r3_proxy_authorization_percent_mapping_values_are_redacted(self):
        stream = io.StringIO()
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(3)]
        keys = ("Proxy-Authorization", "proxy_authorization", "proxy authorization")
        logger = logging.getLogger("metroliza_test_proxy_authorization_mapping_keys")
        self._reset_logger(logger)
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(stream)
        handler.setFormatter(RedactingFormatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)

        try:
            for key, marker in zip(keys, markers):
                logger.error(f"%({key})s", {key: marker})
        finally:
            self._reset_logger(logger)

        output = stream.getvalue()
        self.assertFalse(
            any(marker in output for marker in markers),
            "a Proxy-Authorization percent-mapping value bypassed redaction",
        )
        self.assertEqual(output.count("[REDACTED]"), len(markers))

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

    def test_r3_new_managed_handlers_are_prepared_before_add(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            logger = logging.getLogger("metroliza_test_handler_add_ordering")
            self._reset_logger(logger)
            logger.propagate = False
            config = LoggingConfig(logging.DEBUG, logging.ERROR, logging.WARNING)
            observed: list[tuple[bool, int, object]] = []
            original_add_handler = logger.addHandler

            def record_add_state(handler):
                is_file = getattr(handler, "_metroliza_file_handler", False)
                is_console = getattr(handler, "_metroliza_console_handler", False)
                expected_level = logging.ERROR if is_file else logging.WARNING
                observed.append(
                    (
                        is_file or is_console,
                        expected_level,
                        (handler.level, handler.formatter),
                    )
                )
                original_add_handler(handler)

            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                    patch.object(logger, "addHandler", side_effect=record_add_state),
                ):
                    ensure_application_logging(config=config)

                self.assertEqual(len(observed), 3)
                self.assertTrue(
                    all(
                        managed
                        and actual_level == expected_level
                        and type(formatter) is RedactingFormatter
                        for managed, expected_level, (actual_level, formatter) in observed
                    ),
                    "a managed handler became reachable before it was fully hardened",
                )
            finally:
                self._reset_logger(logger)

    def test_r3_unsafe_managed_handlers_are_detached_before_formatter_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            home_log = fake_home / ".metroliza" / "metroliza.log"
            home_log.parent.mkdir(parents=True)
            console_stream = io.StringIO()

            logger = logging.getLogger("metroliza_test_handler_rehardening_ordering")
            self._reset_logger(logger)
            logger.propagate = False
            unsafe_file = logging.handlers.RotatingFileHandler(
                home_log,
                maxBytes=10 * 1024 * 1024,
                backupCount=7,
                encoding="utf-8",
            )
            setattr(unsafe_file, "_metroliza_file_handler", True)
            unsafe_file.setFormatter(logging.Formatter("%(message)s"))
            unsafe_console = logging.StreamHandler(console_stream)
            setattr(unsafe_console, "_metroliza_console_handler", True)
            unsafe_console.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(unsafe_file)
            logger.addHandler(unsafe_console)
            formatter_reachability: list[bool] = []
            original_file_set_formatter = unsafe_file.setFormatter
            original_console_set_formatter = unsafe_console.setFormatter

            def set_file_formatter(formatter):
                formatter_reachability.append(unsafe_file in logger.handlers)
                original_file_set_formatter(formatter)

            def set_console_formatter(formatter):
                formatter_reachability.append(unsafe_console in logger.handlers)
                original_console_set_formatter(formatter)

            config = LoggingConfig(logging.DEBUG, logging.ERROR, logging.WARNING)
            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                    patch.object(unsafe_file, "setFormatter", side_effect=set_file_formatter),
                    patch.object(unsafe_console, "setFormatter", side_effect=set_console_formatter),
                ):
                    ensure_application_logging(config=config)

                self.assertTrue(formatter_reachability)
                self.assertFalse(
                    any(formatter_reachability),
                    "an unsafe managed handler was reformatted while still reachable",
                )
                resulting_file_handlers = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.handlers.RotatingFileHandler)
                ]
                resulting_console_handlers = [
                    handler
                    for handler in logger.handlers
                    if getattr(handler, "_metroliza_console_handler", False)
                ]
                self.assertEqual(len(resulting_file_handlers), 2)
                self.assertEqual(len(resulting_console_handlers), 1)
                self.assertTrue(
                    all(
                        type(handler.formatter) is RedactingFormatter
                        for handler in (*resulting_file_handlers, *resulting_console_handlers)
                    )
                )
                for original in (unsafe_file, unsafe_console):
                    if original not in logger.handlers:
                        self.assertTrue(original._closed)
            finally:
                self._reset_logger(logger)

    def test_r3_removed_managed_handlers_are_hardened_before_close(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            obsolete_log = root / "obsolete" / "metroliza.log"
            obsolete_log.parent.mkdir(parents=True)
            console_stream = io.StringIO()

            logger = logging.getLogger("metroliza_test_removed_handler_hardening")
            self._reset_logger(logger)
            logger.propagate = False
            obsolete_file = logging.handlers.RotatingFileHandler(
                obsolete_log,
                maxBytes=10 * 1024 * 1024,
                backupCount=7,
                encoding="utf-8",
            )
            setattr(obsolete_file, "_metroliza_file_handler", True)
            obsolete_file.setFormatter(logging.Formatter("%(message)s"))
            disabled_console = logging.StreamHandler(console_stream)
            setattr(disabled_console, "_metroliza_console_handler", True)
            disabled_console.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(obsolete_file)
            logger.addHandler(disabled_console)
            formatter_reachability: list[bool] = []
            original_file_set_formatter = obsolete_file.setFormatter
            original_console_set_formatter = disabled_console.setFormatter

            def set_file_formatter(formatter):
                formatter_reachability.append(obsolete_file in logger.handlers)
                original_file_set_formatter(formatter)

            def set_console_formatter(formatter):
                formatter_reachability.append(disabled_console in logger.handlers)
                original_console_set_formatter(formatter)

            config = LoggingConfig(logging.INFO, logging.INFO, None)
            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                    patch.object(obsolete_file, "setFormatter", side_effect=set_file_formatter),
                    patch.object(
                        disabled_console,
                        "setFormatter",
                        side_effect=set_console_formatter,
                    ),
                ):
                    ensure_application_logging(config=config)

                self.assertTrue(formatter_reachability)
                self.assertFalse(
                    any(formatter_reachability),
                    "a removed handler was hardened while still reachable",
                )
                for held_handler in (obsolete_file, disabled_console):
                    self.assertNotIn(held_handler, logger.handlers)
                    self.assertTrue(held_handler._closed)
                    self.assertIs(type(held_handler.formatter), RedactingFormatter)
            finally:
                self._reset_logger(logger)

    def test_r3_duplicate_managed_handlers_are_collapsed_and_closed_safely(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            home_log = fake_home / ".metroliza" / "metroliza.log"
            home_log.parent.mkdir(parents=True)

            logger = logging.getLogger("metroliza_test_duplicate_managed_handlers")
            self._reset_logger(logger)
            logger.propagate = False
            duplicate_files = [
                logging.handlers.RotatingFileHandler(
                    home_log,
                    maxBytes=10 * 1024 * 1024,
                    backupCount=7,
                    encoding="utf-8",
                )
                for _ in range(2)
            ]
            duplicate_consoles = [logging.StreamHandler(io.StringIO()) for _ in range(2)]
            for handler in duplicate_files:
                setattr(handler, "_metroliza_file_handler", True)
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
            for handler in duplicate_consoles:
                setattr(handler, "_metroliza_console_handler", True)
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)

            config = LoggingConfig(logging.INFO, logging.INFO, logging.INFO)
            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                ):
                    ensure_application_logging(config=config)

                resulting_files = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.handlers.RotatingFileHandler)
                ]
                resulting_consoles = [
                    handler
                    for handler in logger.handlers
                    if getattr(handler, "_metroliza_console_handler", False)
                ]
                self.assertEqual(len(resulting_files), 2)
                self.assertEqual(
                    len({Path(handler.baseFilename).resolve() for handler in resulting_files}),
                    2,
                )
                self.assertEqual(len(resulting_consoles), 1)
                self.assertTrue(
                    all(
                        type(handler.formatter) is RedactingFormatter
                        for handler in (*resulting_files, *resulting_consoles)
                    )
                )

                removed_files = [
                    handler for handler in duplicate_files if handler not in logger.handlers
                ]
                removed_consoles = [
                    handler for handler in duplicate_consoles if handler not in logger.handlers
                ]
                self.assertEqual(len(removed_files), 1)
                self.assertEqual(len(removed_consoles), 1)
                for held_handler in (*removed_files, *removed_consoles):
                    self.assertTrue(held_handler._closed)
                    self.assertIs(type(held_handler.formatter), RedactingFormatter)
            finally:
                self._reset_logger(logger)

    def test_r3_repeated_fallback_setup_retains_one_managed_sink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home_file"
            fake_home.write_text("not a directory", encoding="utf-8")
            fake_cwd = root / "cwd_file"
            fake_cwd.write_text("not a directory", encoding="utf-8")
            fallback_root = root / "runtime"
            logger = logging.getLogger("metroliza_test_repeated_fallback_setup")
            self._reset_logger(logger)
            logger.propagate = False
            config = LoggingConfig(logging.INFO, logging.INFO, None)

            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                    patch(
                        "metroliza.shared.logging_utils.tempfile.gettempdir",
                        return_value=str(fallback_root),
                    ),
                ):
                    ensure_application_logging(config=config)
                    first_handlers = tuple(logger.handlers)
                    ensure_application_logging(config=config)

                fallback_handlers = [
                    handler
                    for handler in logger.handlers
                    if getattr(handler, "_metroliza_file_handler", False)
                ]
                self.assertEqual(len(first_handlers), 1)
                self.assertEqual(len(fallback_handlers), 1)
                self.assertIs(fallback_handlers[0], first_handlers[0])
                self.assertFalse(fallback_handlers[0]._closed)
                self.assertIs(type(fallback_handlers[0].formatter), RedactingFormatter)
                self.assertEqual(
                    Path(fallback_handlers[0].baseFilename).resolve(),
                    (fallback_root / "metroliza" / "metroliza.log").resolve(),
                )
            finally:
                self._reset_logger(logger)

    def test_r3_aliased_primary_paths_create_one_rotating_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = fake_home / ".metroliza"
            fake_cwd.mkdir()
            logger = logging.getLogger("metroliza_test_aliased_primary_paths")
            self._reset_logger(logger)
            logger.propagate = False
            config = LoggingConfig(logging.INFO, logging.INFO, None)

            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                ):
                    ensure_application_logging(config=config)
                    first_handlers = tuple(logger.handlers)
                    ensure_application_logging(config=config)

                file_handlers = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.handlers.RotatingFileHandler)
                ]
                self.assertEqual(len(first_handlers), 1)
                self.assertEqual(len(file_handlers), 1)
                self.assertEqual(
                    Path(file_handlers[0].baseFilename).resolve(),
                    (fake_cwd / "metroliza.log").resolve(),
                )
                self.assertIs(type(file_handlers[0].formatter), RedactingFormatter)
            finally:
                self._reset_logger(logger)

    def test_r3_concurrent_setup_is_serialized_without_duplicate_handlers(self):
        class CoordinatedLock:
            def __init__(self):
                self._lock = threading.RLock()
                self._state_lock = threading.Lock()
                self._second_attempt = threading.Event()
                self.attempts = 0
                self.active = 0
                self.max_active = 0

            def __enter__(self):
                with self._state_lock:
                    self.attempts += 1
                    attempt = self.attempts
                if attempt == 1:
                    self._lock.acquire()
                    if not self._second_attempt.wait(timeout=5):
                        self._lock.release()
                        raise AssertionError("second setup did not attempt serialized entry")
                else:
                    self._second_attempt.set()
                    self._lock.acquire()
                with self._state_lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                with self._state_lock:
                    self.active -= 1
                self._lock.release()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            logger = logging.getLogger("metroliza_test_serialized_setup")
            self._reset_logger(logger)
            logger.propagate = False
            config = LoggingConfig(logging.INFO, logging.INFO, logging.INFO)
            coordinated_lock = CoordinatedLock()
            start = threading.Barrier(2)
            failures: list[str] = []

            def configure():
                try:
                    start.wait()
                    ensure_application_logging(config=config)
                except BaseException as exc:
                    failures.append(type(exc).__name__)

            workers = [threading.Thread(target=configure) for _ in range(2)]
            try:
                with (
                    patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
                    patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
                    patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
                    patch.object(
                        logging_utils_module,
                        "_LOGGING_SETUP_LOCK",
                        coordinated_lock,
                        create=True,
                    ),
                ):
                    for worker in workers:
                        worker.start()
                    for worker in workers:
                        worker.join(timeout=10)

                self.assertFalse(any(worker.is_alive() for worker in workers))
                self.assertFalse(failures)
                self.assertEqual(coordinated_lock.attempts, 2)
                self.assertEqual(coordinated_lock.max_active, 1)
                self.assertEqual(len(logger.handlers), 3)
                self.assertEqual(len({id(handler) for handler in logger.handlers}), 3)
                self.assertTrue(
                    all(
                        type(handler.formatter) is RedactingFormatter for handler in logger.handlers
                    )
                )
            finally:
                self._reset_logger(logger)

    def test_r3_repeated_setup_reuses_handlers_and_one_redacting_formatter_layer(self):
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
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ):
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
