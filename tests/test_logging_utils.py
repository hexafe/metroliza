import base64
import io
import json
import logging
import logging.handlers
import tempfile
import threading
import time
import unittest
import uuid
from abc import ABCMeta
from collections import defaultdict, deque
from collections.abc import Mapping as AbstractMapping
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from modules.logging_utils import ensure_application_logging, resolve_logging_config
from metroliza.shared.logging_utils import redact_log_text


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

    def test_formatter_redacts_custom_level_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            custom_level = logging.ERROR + 7
            original_level_name = logging.getLevelName(custom_level)

            logger = logging.getLogger("metroliza_test_logging_level_name")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                logging.addLevelName(custom_level, f"password={marker}")
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.log(custom_level, "safe level diagnostic")

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(marker, home_log)
                self.assertIn("[REDACTED]", home_log)
                self.assertIn("safe level diagnostic", home_log)
            finally:
                logging.addLevelName(custom_level, original_level_name)
                self._reset_logger(logger)

    def test_managed_handlers_redact_messages_exceptions_and_stack(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            console = io.StringIO()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_redaction")
            self._reset_logger(logger)
            logger.propagate = False

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", console):
                    ensure_application_logging(level=logging.INFO)
                    logger.error(
                        "request failed for postgresql://synthetic:%s@localhost/db",
                        marker,
                    )
                    try:
                        try:
                            raise ValueError(f"password={marker}")
                        except ValueError as inner:
                            raise RuntimeError(f"query={marker}") from inner
                    except RuntimeError:
                        logger.exception("database request failed")

                    record = logger.makeRecord(
                        logger.name,
                        logging.ERROR,
                        __file__,
                        1,
                        "stack diagnostic",
                        (),
                        None,
                    )
                    record.stack_info = f"source={marker}"
                    logger.handle(record)
                    logger.info("safe operation completed")

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                for output in (home_log, console.getvalue()):
                    self.assertNotIn(marker, output)
                    self.assertIn("RuntimeError", output)
                    self.assertIn("ValueError", output)
                    self.assertIn("chain=present", output)
                    self.assertIn("traceback=present", output)
                    self.assertIn("stack=present", output)
                    self.assertIn("safe operation completed", output)
                    self.assertIn("[metroliza_test_logging_redaction]", output)
            finally:
                self._reset_logger(logger)

    def test_managed_handlers_redact_recognizable_direct_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()

            logger = logging.getLogger("metroliza_test_logging_direct_redaction")
            self._reset_logger(logger)
            logger.propagate = False

            templates = (
                "password=%s",
                "api_key: %s",
                "access_token=%s",
                "refresh-token=%s",
                "credential=%s",
                "Authorization: Bearer %s",
                'Authorization: "Bearer %s"',
                "Authorization: Basic %s",
                "Authorization: Digest realm=local,token=%s",
                "Proxy-Authorization: Bearer %s",
                "mongodb://synthetic:%s@localhost/db",
                "redis://:%s@localhost/0",
                "redis://%s:@localhost/0",
                "Driver=SQLite;Password=%s;Server=localhost",
                "dsn=Server=localhost;AccessToken=%s",
                "client_" "secret='%s'",
                "secret=%s",
                "auth=%s",
                "authentication=%s",
                "private_key=%s",
                "private key=%s",
                "api key=%s",
                "secret key=%s",
                "password hash=%s",
                "passphrase=%s",
                "cookie=%s",
                "sessionToken=%s",
                "dbPassword=%s",
                "bearerToken=%s",
                "DBPASSWORD=%s",
                "DBPWD=%s",
                "SESSIONTOKEN=%s",
                "PASSWORDHASH=%s",
                "password=prefix,%s",
                "token=prefix\n%s",
                "query=%s",
                "query=SELECT safe,%s",
                "source=%s",
                "source=return safe;%s",
                "path=/synthetic/%s",
                "path=/safe,%s",
                "sensitive_path=/synthetic/%s",
                "x://synthetic:%s@localhost/db",
                f"{'a' * 33}://synthetic:%s@localhost/db",
                "//synthetic:%s@localhost/db",
                "-----BEGIN " "PRIVATE KEY-----\n%s\n-----END PRIVATE KEY-----",
                "-----BEGIN OPENSSH " "PRIVATE KEY-----\n%s",
                "-----BEGIN PGP PRIVATE KEY BLOCK-----\n%s",
                "PuTTY-User-Key-File-3: ssh-rsa\nPrivate-Lines: 1\n%s",
                '{"api key":"%s"}',
                '{"private key":"%s"}',
                '{"secret key":"%s"}',
                '{"password hash":"%s"}',
                '{"connection string":"%s"}',
                '{"sql text":"%s"}',
                '{"sql statement":"%s"}',
            )
            markers = [f"generated-{uuid.uuid4().hex}" for _ in templates]
            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    for template, marker in zip(templates, markers, strict=True):
                        logger.error(template, marker)
                    logger.info("tokenizer=wordpiece status=ok")
                    logger.info("secretary=alice operation=complete")
                    logger.info("passwordless=true backend=webauthn")
                    logger.info("ordinary safe diagnostic remains readable")

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                for marker in markers:
                    self.assertNotIn(marker, home_log)
                self.assertIn("tokenizer=wordpiece status=ok", home_log)
                self.assertIn("secretary=alice operation=complete", home_log)
                self.assertIn("passwordless=true backend=webauthn", home_log)
                self.assertIn("ordinary safe diagnostic remains readable", home_log)
            finally:
                self._reset_logger(logger)

    def test_redaction_handles_mapping_nonstring_and_malformed_arguments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            console = io.StringIO()
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(21)]

            class SensitiveObject:
                def __str__(self):
                    return f"token={markers[1]}"

            class SafeCount(IntEnum):
                THREE = 3

            logger = logging.getLogger("metroliza_test_logging_arguments")
            self._reset_logger(logger)
            logger.propagate = False

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", console):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("%(credential)s", {"credential": markers[0]})
                    logger.error("object=%s", SensitiveObject())
                    logger.error("malformed password=%s %s", markers[2])
                    logger.error("%(db_password)s", {"db_password": markers[3]})
                    logger.error("%(auth_token)s", {"auth_token": markers[4]})
                    logger.error("%(session_token)s", {"session_token": markers[5]})
                    logger.error("%(secret_key)s", {"secret_key": markers[6]})
                    logger.error("%(auth)s", {"auth": markers[7]})
                    logger.error("%(authentication)s", {"authentication": markers[8]})
                    logger.error("%(private_key)s", {"private_key": markers[9]})
                    logger.error("%(passphrase)s", {"passphrase": markers[10]})
                    logger.error("%(cookie)s", {"cookie": markers[11]})

                    class DisguisedPasswordKey(str):
                        def strip(self, _characters=None):
                            return "ordinary_field"

                    logger.error(
                        "%s",
                        {DisguisedPasswordKey("password"): markers[12]},
                    )
                    logger.error("%(sessionToken)s", {"sessionToken": markers[13]})
                    logger.error("%(dbPassword)s", {"dbPassword": markers[14]})
                    logger.error("%(bearerToken)s", {"bearerToken": markers[15]})
                    logger.error("%(userPassword)s", {"userPassword": markers[16]})
                    logger.error("%(DBPASSWORD)s", {"DBPASSWORD": markers[17]})
                    logger.error("%(SESSIONTOKEN)s", {"SESSIONTOKEN": markers[18]})
                    logger.error("%(passwordhash)s", {"passwordhash": markers[19]})
                    logger.error("%(PASSWORDHASH)s", {"PASSWORDHASH": markers[20]})
                    logger.info("%(resource_count)s", {"resource_count": 4})
                    logger.info("%(tokenizer_name)s", {"tokenizer_name": "wordpiece"})
                    logger.info("%(pathology_result)s", {"pathology_result": "benign"})
                    logger.info("enum count=%d", SafeCount.THREE)
                    logger.info("default count=%d", defaultdict(int, count=5)["count"])
                    logger.info("%(count)d", defaultdict(int, count=6))
                    logger.info("safe count=%d", 3)

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                for output in (home_log, console.getvalue()):
                    for marker in markers:
                        self.assertNotIn(marker, output)
                    self.assertIn("format_error=present", output)
                    self.assertIn("wordpiece", output)
                    self.assertIn("benign", output)
                    self.assertIn("enum count=3", output)
                    self.assertIn("default count=5", output)
                    self.assertIn("[MainThread] 6", output)
                    self.assertIn("safe count=3", output)
            finally:
                self._reset_logger(logger)

    def test_redaction_of_long_nonmatching_labels_is_bounded(self):
        text = "a-" * 40000

        started = time.perf_counter()
        output = redact_log_text(text)
        elapsed = time.perf_counter() - started

        self.assertEqual(
            output,
            "log_text=[REDACTED]; log_text_truncated=present",
        )
        self.assertLess(elapsed, 1.0)

    def test_redaction_covers_encoded_labels_uris_and_private_key_formats(self):
        marker = f"generated-{uuid.uuid4().hex}"
        sensitive_values = (
            rf'{{"p\u0061ssword":"{marker}"}}',
            rf'{{"api\u0020key":"{marker}"}}',
            rf'{{"private\u0020key":"{marker}"}}',
            f'{{"password"\n:\n"{marker}"}}',
            f'{{"db:password":"{marker}"}}',
            f'{{"db=password":"{marker}"}}',
            f"password\n={marker}",
            f"can't connect; password: {marker}",
            f'prefix "unterminated password: {marker}',
            f'config says "password: {marker}" end',
            f"{'a' * 257}_password={marker}",
            f"api.key={marker}",
            f"private.key={marker}",
            f"password.hash={marker}",
            f"connection.string={marker}",
            f"sql.statement={marker}",
            f"source.code={marker}",
            f"password[0]={marker}",
            f"api[key]={marker}",
            f"private/key={marker}",
            f"pass%77ord={marker}",
            f"api%5Fkey={marker}",
            f"private%20key={marker}",
            f"api+key={marker}",
            f"password%3D{marker}",
            f"password%253D{marker}",
            f"payload%3Dpassword%253D{marker}",
            (
                "%257B%2522password%2522%253A%2522"
                f"{marker}%2522%257D"
            ),
            rf"passw\u006frd%3D{marker}",
            rf"data\u003aapplication%2Fpkcs8%3Bbase64%2C{marker}",
            f"api%5Fkey%3D{marker}",
            f"dbpass={marker}",
            f"user_pass={marker}",
            f"pass={marker}",
            f"statement=SELECT value FROM local_table WHERE value='{marker}'",
            f"db.statement=SELECT '{marker}'",
            f"AccountKey={marker}",
            f"SharedAccessKey={marker}",
            f"SharedAccessSignature={marker}",
            rf'{{"url":"https:\/\/alice:{marker}\u0040example.test"}}',
            rf'{{"url":"https:\u002f\u002falice:{marker}\u0040example.test"}}',
            rf'{{"url":"sip:alice:{marker}\u0040example.test"}}',
            rf'{{"url":"sips:alice:{marker}\u0040example.test"}}',
            rf'{{"url":"sip\u003aalice:{marker}\u0040example.test"}}',
            (
                rf'{{"blob":"-----BEGIN PRIV\u0041TE KEY-----\n{marker}'
                r'\n-----END PRIVATE KEY-----"}'
            ),
            rf'{{"blob":"data\u003aapplication/pkcs8;base64,{marker}"}}',
            (
                'payload: {"msg":"passw\\u006frd='
                f'{marker}"}} status=failed'
            ),
            (
                'payload: {"blob":"-----BEGIN PRIV\\u0041TE KEY-----\\n'
                f'{marker}"}} status=failed'
            ),
            json.dumps(
                {
                    "payload": (
                        rf'{{"msg":"passw\u006frd={marker}"}}'
                    )
                },
                separators=(",", ":"),
            ),
            json.dumps(
                {"body": f"password%3D{marker}"},
                separators=(",", ":"),
            ),
            json.dumps(
                {"body": f"api%5Fkey%3D{marker}"},
                separators=(",", ":"),
            ),
            json.dumps(
                {"body": f"password%253D{marker}"},
                separators=(",", ":"),
            ),
            f"password_{marker}=safe",
            f"api_key_{marker}=safe",
            f"DBPWD_{marker}: safe",
            f'{{"password_{marker}":"safe"}}',
            f"{{'password_{marker}': 'safe'}}",
            f"url=https%3A%2F%2Falice%3A{marker}%40example.test",
            f"sip:alice:{marker}@example.test",
            f"sips:alice:{marker}@example.test",
            f"--password {marker}",
            f"requirepass {marker}",
            f"machine local.test login synthetic password {marker}",
            f"IdentityFile /tmp/{marker}",
            f"client-key-data={marker}",
            f"client-key={marker}",
            f"sslkey=/tmp/{marker}",
            f"tls_key=/tmp/{marker}",
            f"-----BEGIN {'PRIVATE'} KEY-----\n{marker}\n-----END PRIVATE KEY-----",
            f"  PuTTY-User-Key-File-3: ssh-rsa\nPrivate-Lines: 1\n{marker}",
            f"---- BEGIN SSH2 ENCRYPTED PRIVATE KEY ----\n{marker}",
            f"AGE-SECRET-KEY-1{marker}",
            f"untrusted comment: minisign encrypted secret key\n{marker}",
            f"untrusted comment: signify secret key\n{marker}",
            f"data:application/pkcs8;base64,{marker}",
            f"data:application/pkcs8-encrypted;base64,{marker}",
            f"data:application/x-pkcs8;charset=utf-8;base64,{marker}",
            f"data:application/pkcs8;name=urn:example:key;base64,{marker}",
            f"data:application/pkcs12;base64,{marker}",
            rf'{{"kty":"RSA","n":"local","e":"AQAB","d":"{marker}"}}',
            rf'{{"k\u0074y":"RSA","\u0064":"{marker}"}}',
            rf'{{"kty":"oct","k":"{marker}"}}',
            (
                "payload=%7B%22kty%22%3A%22oct%22%2C%22k%22%3A%22"
                f"{marker}%22%7D"
            ),
            f"payload=password%3D{marker}",
            (
                "payload=%7B%22password%22%3A%22"
                f"{marker}%22%7D"
            ),
            (
                "data:application/jwk+json,%7B%22kty%22%3A%22RSA%22%2C"
                f"%22d%22%3A%22{marker}%22%7D"
            ),
            f"data:application/jwk-set+json;base64,{marker}",
            (
                '{"keys":[{"kty":"RSA","n":"local","e":"AQAB"},'
                f'{{"kty":"EC","crv":"P-256","d":"{marker}"}}]}}'
            ),
        )

        for value in sensitive_values:
            with self.subTest(value=value[:80]):
                output = redact_log_text(value)
                self.assertNotIn(marker, output)
                self.assertIn("[REDACTED]", output)

        safe_values = (
            "jquery=3.7.1",
            "jquery_version=3.7.1",
            "telepath=enabled",
            "resource=cache",
            "resource_count=4",
            "compass=north",
            "bypass=disabled",
            "token bucket refill completed",
            "token count is 4",
            "secret sharing completed",
            "API key rotation completed",
            "private key rotation completed",
            "sip:alice@example.test",
            "malformed%2label=visible",
        )
        for value in safe_values:
            with self.subTest(value=value):
                self.assertEqual(redact_log_text(value), value)

        safe_json = "{" + ",".join(
            f'"field{index}":{index}' for index in range(129)
        ) + "}"
        self.assertEqual(redact_log_text(safe_json), safe_json)

        for scalar in ("1", "true", "null", "x"):
            safe_scalar_array = json.dumps(
                [scalar] * 2050,
                separators=(",", ":"),
            )
            with self.subTest(scalar=scalar):
                self.assertEqual(
                    redact_log_text(safe_scalar_array),
                    safe_scalar_array,
                )

    def test_redaction_covers_private_jwk_mapping_order_and_nested_extras(self):
        markers = [f"generated-{uuid.uuid4().hex}" for _ in range(6)]
        direct = {"kty": "RSA", "d": markers[0], "n": "local"}
        nested = {"keys": [{"kty": "oct", "k": markers[1]}]}
        late_type = {"k": markers[2]}
        late_type.update({f"field{index}": index for index in range(128)})
        late_type["kty"] = "oct"

        class StringKey(str):
            pass

        hostile_rsa = {StringKey("kty"): "RSA", "d": markers[3]}
        hostile_oct = {StringKey("kty"): "oct", "k": markers[4]}
        encoded_form = {"body": f"password%3D{markers[5]}"}

        for value, marker in zip(
            (
                direct,
                nested,
                late_type,
                hostile_rsa,
                hostile_oct,
                encoded_form,
            ),
            markers,
            strict=True,
        ):
            with self.subTest(marker=marker):
                output = redact_log_text(value)
                self.assertNotIn(marker, output)
                self.assertIn("[REDACTED]", output)

    def test_redaction_scanners_remain_linear_at_the_text_budget(self):
        probes = (
            "a" * 65536,
            ("abc-def." * 8192)[:65536],
            ("data:application/pkcs8;" * 2800)[:65536],
            ("untrusted comment: minisign public key " * 1800)[:65536],
            ('{"kty":"RSA"} ' * 5000)[:65536],
        )

        for probe in probes:
            started = time.perf_counter()
            output = redact_log_text(probe)
            elapsed = time.perf_counter() - started

            self.assertLessEqual(len(output), 65536)
            self.assertLess(elapsed, 1.0)

    def test_jwk_data_uri_preserves_public_keys_and_redacts_private_keys(self):
        marker = f"generated-{uuid.uuid4().hex}"
        public_json = '{"kty":"RSA","n":"local","e":"AQAB"}'
        private_json = f'{{"kty":"RSA","n":"local","d":"{marker}"}}'
        public_payload = base64.b64encode(public_json.encode()).decode()
        private_payload = base64.b64encode(private_json.encode()).decode()
        public_uri = f"data:application/jwk+json;base64,{public_payload}"
        private_uri = f"data:application/jwk-set+json;base64,{private_payload}"
        non_base64_metadata = (
            "data:application/jwk+json;encoding=notbase64,"
            "%7B%22kty%22%3A%22RSA%22%2C%22n%22%3A%22local%22%7D"
        )

        self.assertEqual(redact_log_text(public_uri), public_uri)
        self.assertEqual(
            redact_log_text(non_base64_metadata),
            non_base64_metadata,
        )
        self.assertEqual(redact_log_text(private_uri), "[REDACTED]")

    def test_credential_uri_scanner_preserves_query_and_fragment_emails(self):
        safe_values = (
            "https://example.test?email=user@example.net",
            "https://example.test#owner=user@example.net",
        )

        for value in safe_values:
            self.assertEqual(redact_log_text(value), value)

    def test_redaction_of_shared_container_dag_has_global_bound(self):
        shared: object = ["safe"]
        for _ in range(4):
            shared = [shared] * 10

        started = time.perf_counter()
        output = redact_log_text(shared)
        elapsed = time.perf_counter() - started

        self.assertIn("repeated_argument=present", output)
        self.assertLess(elapsed, 1.0)

    def test_malformed_message_retains_safe_exception_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_malformed_exception")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    try:
                        raise RuntimeError(f"password={marker}")
                    except RuntimeError:
                        logger.error("broken %s %s", "one", exc_info=True)

                output = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(marker, output)
                self.assertIn("RuntimeError", output)
                self.assertIn("traceback=present", output)
                self.assertIn("format_error=present", output)
            finally:
                self._reset_logger(logger)

    def test_exception_objects_cannot_bypass_message_redaction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            console = io.StringIO()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_exception_arguments")
            self._reset_logger(logger)
            logger.propagate = False

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", console):
                    ensure_application_logging(level=logging.INFO)
                    try:
                        try:
                            raise ValueError(marker)
                        except ValueError as inner:
                            raise RuntimeError(marker) from inner
                    except RuntimeError as exception:
                        class ExceptionWrapper:
                            def __init__(self, error):
                                self.error = error

                            def __str__(self):
                                return str(self.error)

                        class ListWrapper(list):
                            def __iter__(self):
                                return iter([str(list.__getitem__(self, 0))])

                        class MappingWrapper(dict):
                            def items(self):
                                return {"safe": str(dict.__getitem__(self, "error"))}.items()

                        logger.exception("tuple event %s", exception)
                        logger.exception("mapping event %(error)s", {"error": exception})
                        logger.error(exception)
                        logger.error("nested event %s", [exception])
                        logger.error("namespace event %s", SimpleNamespace(error=exception))
                        logger.error("deque event %s", deque([exception]))
                        logger.error("wrapper event %s", ExceptionWrapper(exception))
                        logger.error("list subclass event %s", ListWrapper([exception]))
                        logger.error(
                            "mapping subclass event %s",
                            MappingWrapper(error=exception),
                        )

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                for output in (home_log, console.getvalue()):
                    self.assertNotIn(marker, output)
                    self.assertIn("tuple event", output)
                    self.assertIn("mapping event", output)
                    self.assertIn("nested event", output)
                    self.assertIn("namespace event", output)
                    self.assertIn("deque event", output)
                    self.assertIn("wrapper event", output)
                    self.assertIn("list subclass event", output)
                    self.assertIn("mapping subclass event", output)
                    self.assertIn("RuntimeError", output)
                    self.assertIn("ValueError", output)
            finally:
                self._reset_logger(logger)

    def test_repeated_setup_is_idempotent_with_one_redaction_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_idempotent_redaction")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    ensure_application_logging(level=logging.INFO)
                    logger.error("event-id=one password=%s", marker)

                file_handlers = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.handlers.RotatingFileHandler)
                ]
                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(len(file_handlers), 2)
                self.assertEqual(home_log.count("event-id=one"), 1)
                self.assertEqual(home_log.count("[REDACTED]"), 1)
                self.assertNotIn(marker, home_log)
            finally:
                self._reset_logger(logger)

    def test_managed_handler_failure_never_dumps_raw_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            failure_notice = io.StringIO()

            class FailingStream:
                def write(self, _value):
                    raise OSError("synthetic local stream failure")

                def flush(self):
                    return None

            logger = logging.getLogger("metroliza_test_logging_handler_failure")
            self._reset_logger(logger)
            logger.propagate = False

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ):
                    ensure_application_logging(level=logging.INFO)

                console_handler = next(
                    handler
                    for handler in logger.handlers
                    if getattr(handler, "_metroliza_console_handler", False)
                )
                console_handler.setStream(FailingStream())
                with patch("sys.stderr", failure_notice):
                    logger.error("password=%s", marker)

                self.assertNotIn(marker, failure_notice.getvalue())
                self.assertIn("record suppressed", failure_notice.getvalue())
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_retires_managed_handler_with_unsafe_error_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            failure_notice = io.StringIO()

            class FailingStream:
                def write(self, _value):
                    raise OSError("synthetic local stream failure")

                def flush(self):
                    return None

            from metroliza.shared import logging_utils

            class UnsafePretender(logging_utils._SafeStreamHandler):
                def handleError(self, record):
                    logging.Handler.handleError(self, record)

            logger = logging.getLogger("metroliza_test_logging_unsafe_pretender")
            self._reset_logger(logger)
            logger.propagate = False
            unsafe_handler = UnsafePretender(FailingStream())
            setattr(unsafe_handler, "_metroliza_console_handler", True)
            logger.addHandler(unsafe_handler)

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", failure_notice):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                self.assertNotIn(unsafe_handler, logger.handlers)
                self.assertNotIn(marker, failure_notice.getvalue())
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_hardens_preexisting_standard_handlers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            legacy_log_path = root / "legacy.log"
            legacy_console = io.StringIO()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_preexisting_handlers")
            self._reset_logger(logger)
            logger.propagate = False
            legacy_file_handler = logging.FileHandler(legacy_log_path, encoding="utf-8")
            legacy_console_handler = logging.StreamHandler(legacy_console)
            logger.addHandler(legacy_file_handler)
            logger.addHandler(legacy_console_handler)

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                legacy_output = legacy_log_path.read_text(encoding="utf-8")
                for output in (legacy_output, legacy_console.getvalue()):
                    self.assertNotIn(marker, output)
                    self.assertIn("[REDACTED]", output)
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_suppresses_legacy_standard_handler_error_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            failure_notice = io.StringIO()

            class FailingStream:
                def write(self, _value):
                    raise OSError(f"password={marker}")

                def flush(self):
                    return None

            logger = logging.getLogger("metroliza_test_logging_legacy_handler_failure")
            self._reset_logger(logger)
            logger.propagate = False
            legacy_handler = logging.StreamHandler(FailingStream())
            logger.addHandler(legacy_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", failure_notice):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("safe event")

                self.assertNotIn(marker, failure_notice.getvalue())
                self.assertIn("record suppressed", failure_notice.getvalue())
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_preserves_custom_handler_with_safe_record_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            captured: list[str] = []

            class CapturingHandler(logging.Handler):
                def emit(self, record):
                    captured.append(
                        f"{record.msg}; message={getattr(record, 'message', None)}; "
                        f"args={record.args}; exc_info={record.exc_info}; "
                        f"record_type={type(record).__name__}"
                    )

            logger = logging.getLogger("metroliza_test_logging_custom_handler")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = CapturingHandler()
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    try:
                        raise RuntimeError(f"password={marker}")
                    except RuntimeError:
                        logger.exception("request token=%s", marker)
                    cached_record = logger.makeRecord(
                        logger.name,
                        logging.ERROR,
                        __file__,
                        1,
                        "safe cached diagnostic",
                        (),
                        None,
                    )
                    cached_record.message = f"password={marker}"
                    logger.handle(cached_record)

                    class CustomLogRecord(logging.LogRecord):
                        pass

                    logger.handle(
                        CustomLogRecord(
                            logger.name,
                            logging.INFO,
                            __file__,
                            1,
                            "subclass safe diagnostic",
                            (),
                            None,
                        )
                    )

                self.assertIn(custom_handler, logger.handlers)
                self.assertTrue(captured)
                self.assertNotIn(marker, "".join(captured))
                self.assertIn("[REDACTED]", "".join(captured))
                self.assertIn("RuntimeError", "".join(captured))
                self.assertIn("message=safe cached diagnostic", "".join(captured))
                self.assertIn("subclass safe diagnostic", "".join(captured))
                self.assertIn("exc_info=None", "".join(captured))
                self.assertIn("record_type=LogRecord", "".join(captured))
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_preserves_unmanaged_formatter_and_filter_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            stream = io.StringIO()
            filter_observations: list[bool] = []

            class TemplateFilter(logging.Filter):
                def filter(self, record):
                    matched = record.msg == "value=%s" and record.args == (7,)
                    filter_observations.append(matched)
                    return matched

            class DelegatingHandler(logging.StreamHandler):
                def handle(self, record):
                    return super().handle(record)

            logger = logging.getLogger("metroliza_test_logging_handler_contract")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = DelegatingHandler(stream)
            custom_formatter = logging.Formatter("CUSTOM|%(levelname)s|%(message)s")
            custom_handler.setFormatter(custom_formatter)
            custom_handler.addFilter(TemplateFilter())
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("value=%s", 7)

                self.assertIs(custom_handler.formatter, custom_formatter)
                self.assertEqual(filter_observations, [True])
                self.assertEqual(stream.getvalue(), "CUSTOM|INFO|value=7\n")
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_redacts_text_created_by_unmanaged_formatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            stream = io.StringIO()

            logger = logging.getLogger("metroliza_test_logging_formatter_output")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = logging.StreamHandler(stream)
            custom_formatter = logging.Formatter("CUSTOM|password=%(message)s")
            custom_handler.setFormatter(custom_formatter)
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("%s", marker)

                self.assertIs(custom_handler.formatter, custom_formatter)
                self.assertNotIn(marker, stream.getvalue())
                self.assertIn("CUSTOM|password=[REDACTED]", stream.getvalue())
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_preserves_standard_pathname_formatter_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            stream = io.StringIO()

            logger = logging.getLogger("metroliza_test_logging_pathname_formatter")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = logging.StreamHandler(stream)
            custom_handler.setFormatter(
                logging.Formatter(
                    "%(pathname)s|%(filename)s|%(module)s|%(funcName)s|%(message)s"
                )
            )
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    record = logger.makeRecord(
                        logger.name,
                        logging.INFO,
                        "/safe/app.py",
                        1,
                        "safe event",
                        (),
                        None,
                    )
                    logger.handle(record)
                    marker = f"generated-{uuid.uuid4().hex}"
                    hostile_record = logger.makeRecord(
                        logger.name,
                        logging.INFO,
                        f"/synthetic/{marker}/app.py",
                        1,
                        "safe hostile-core event",
                        (),
                        None,
                        func=marker,
                    )
                    hostile_record.filename = marker
                    hostile_record.module = marker
                    logger.handle(hostile_record)

                self.assertIn(
                    "[REDACTED]|[REDACTED]|[REDACTED]|[REDACTED]|safe event",
                    stream.getvalue(),
                )
                self.assertNotIn(marker, stream.getvalue())
                self.assertNotIn("format_error=present", stream.getvalue())
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_redacts_custom_emit_already_past_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            filter_entered = threading.Event()
            release_filter = threading.Event()
            captured: list[str] = []

            class PausingFilter(logging.Filter):
                def filter(self, _record):
                    filter_entered.set()
                    return release_filter.wait(timeout=5)

            class CapturingHandler(logging.Handler):
                def emit(self, record):
                    captured.append(str(record.msg))

            logger = logging.getLogger("metroliza_test_logging_custom_handler_race")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            custom_handler = CapturingHandler()
            custom_handler.addFilter(PausingFilter())
            logger.addHandler(custom_handler)
            worker = threading.Thread(
                target=logger.error,
                args=("event-id=custom-race password=%s", marker),
            )

            try:
                worker.start()
                self.assertTrue(filter_entered.wait(timeout=5))
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                release_filter.set()
                worker.join(timeout=5)

                self.assertFalse(worker.is_alive())
                self.assertNotIn(marker, "".join(captured))
                self.assertIn("event-id=custom-race", "".join(captured))
                self.assertIn("[REDACTED]", "".join(captured))
            finally:
                release_filter.set()
                worker.join(timeout=5)
                self._reset_logger(logger)

    def test_reconfiguration_redacts_overridden_handle_already_in_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            handle_entered = threading.Event()
            release_handle = threading.Event()
            captured: list[str] = []

            class OverriddenHandleHandler(logging.Handler):
                def handle(self, record):
                    handle_entered.set()
                    release_handle.wait(timeout=5)
                    self.handleError(record)
                    return True

                def emit(self, record):
                    raise AssertionError("overridden handle uses its error policy")

                def handleError(self, record):
                    captured.append(str(record.msg))

            logger = logging.getLogger("metroliza_test_logging_overridden_handle_race")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            custom_handler = OverriddenHandleHandler()
            logger.addHandler(custom_handler)
            worker = threading.Thread(
                target=logger.error,
                args=("event-id=handle-race password=%s", marker),
            )

            try:
                worker.start()
                self.assertTrue(handle_entered.wait(timeout=5))
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                release_handle.set()
                worker.join(timeout=5)

                self.assertFalse(worker.is_alive())
                self.assertNotIn(marker, "".join(captured))
                self.assertIn("event-id=handle-race", "".join(captured))
                self.assertIn("[REDACTED]", "".join(captured))
            finally:
                release_handle.set()
                worker.join(timeout=5)
                self._reset_logger(logger)

    def test_reconfiguration_preserves_unmanaged_handler_error_policy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            fallback_events: list[str] = []

            class FailoverHandler(logging.Handler):
                def emit(self, record):
                    self.handleError(record)

                def handleError(self, record):
                    fallback_events.append(str(record.msg))

            logger = logging.getLogger("metroliza_test_logging_error_policy")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = FailoverHandler()
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                self.assertEqual(len(fallback_events), 1)
                self.assertNotIn(marker, fallback_events[0])
                self.assertIn("[REDACTED]", fallback_events[0])
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_sanitizes_direct_custom_handle_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            captured: list[str] = []

            class DirectHandleHandler(logging.Handler):
                def handle(self, record):
                    captured.append(record.getMessage())
                    return True

                def emit(self, record):
                    raise AssertionError("direct handle does not delegate to emit")

            logger = logging.getLogger("metroliza_test_logging_direct_handle")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = DirectHandleHandler()
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)
                    logger.error("mapping=%s", {f"password={marker}": "safe"})
                    bare_sensitive_keys = (
                        f"password_{marker}",
                        f"DBPWD_{marker}",
                        f"DBQUERY_{marker}",
                        f"DBSOURCE_{marker}",
                        f"FILEPATH_{marker}",
                        f"SOURCEPATH_{marker}",
                        f"SOURCETEXT_{marker}",
                        f"SOURCECODE_{marker}",
                        f"SENSITIVEPATH_{marker}",
                    )
                    for key in bare_sensitive_keys:
                        logger.error("mapping=%s", {key: "safe"})
                    compact_path_keys = (
                        "filepath",
                        "sourcepath",
                        "sensitivepath",
                        "secretpath",
                        "credentialpath",
                        "passwordpath",
                        "tokenpath",
                        "apikeypath",
                        "clientsecretpath",
                    )
                    for key in compact_path_keys:
                        logger.error(f"%({key})s", {key: f"/synthetic/{marker}"})

                self.assertEqual(
                    len(captured),
                    2 + len(bare_sensitive_keys) + len(compact_path_keys),
                )
                self.assertNotIn(marker, "".join(captured))
                self.assertIn("[REDACTED]", "".join(captured))
                managed_output = (
                    fake_home / ".metroliza" / "metroliza.log"
                ).read_text(encoding="utf-8")
                self.assertNotIn(marker, managed_output)
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_redacts_caller_supplied_diagnostic_carry_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            exception_marker = f"generated-{uuid.uuid4().hex}"
            stack_marker = f"generated-{uuid.uuid4().hex}"
            captured: list[str] = []

            class CapturingHandler(logging.Handler):
                def emit(self, record):
                    captured.append(record.getMessage())

            logger = logging.getLogger("metroliza_test_logging_carry_fields")
            self._reset_logger(logger)
            logger.propagate = False
            custom_handler = CapturingHandler()
            logger.addHandler(custom_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error(
                        "safe diagnostic",
                        extra={
                            "_metroliza_exception_summary": (
                                f"password={exception_marker}"
                            ),
                            "_metroliza_stack_summary": f"token={stack_marker}",
                        },
                    )

                rendered = "".join(captured)
                self.assertNotIn(exception_marker, rendered)
                self.assertNotIn(stack_marker, rendered)
                self.assertIn("safe diagnostic", rendered)
                self.assertGreaterEqual(rendered.count("[REDACTED]"), 2)
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_does_not_execute_injected_get_message_extra(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            calls: list[str] = []
            captured: list[str] = []

            class CapturingHandler(logging.Handler):
                def emit(self, record):
                    captured.append(record.getMessage())

            logger = logging.getLogger("metroliza_test_logging_get_message_extra")
            self._reset_logger(logger)
            logger.propagate = False
            logger.addHandler(CapturingHandler())

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error(
                        "safe diagnostic",
                        extra={"getMessage": lambda: calls.append("executed")},
                    )

                self.assertEqual(calls, [])
                self.assertEqual(captured, ["safe diagnostic"])
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_removes_sensitive_extra_key_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            direct_keys: list[str] = []
            formatted_keys = io.StringIO()

            class DirectKeyHandler(logging.Handler):
                def handle(self, record):
                    direct_keys.append("|".join(record.__dict__))
                    return True

                def emit(self, record):
                    raise AssertionError("direct handler does not delegate")

            class KeyFormatter(logging.Formatter):
                def format(self, record):
                    return "|".join(record.__dict__)

            logger = logging.getLogger("metroliza_test_logging_sensitive_extra_keys")
            self._reset_logger(logger)
            logger.propagate = False
            logger.addHandler(DirectKeyHandler())
            formatted_handler = logging.StreamHandler(formatted_keys)
            formatted_handler.setFormatter(KeyFormatter())
            logger.addHandler(formatted_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error(
                        "safe diagnostic",
                        extra={f"password_{marker}": "safe"},
                    )

                self.assertNotIn(marker, "".join(direct_keys))
                self.assertNotIn(marker, formatted_keys.getvalue())
            finally:
                self._reset_logger(logger)

    def test_handler_added_during_configuration_receives_safe_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            path_requested = threading.Event()
            release_path = threading.Event()
            late_stream = io.StringIO()

            def paused_home():
                path_requested.set()
                release_path.wait(timeout=5)
                return fake_home

            logger = logging.getLogger("metroliza_test_logging_late_handler")
            self._reset_logger(logger)
            logger.propagate = False
            worker = threading.Thread(target=ensure_application_logging)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", side_effect=paused_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    worker.start()
                    self.assertTrue(path_requested.wait(timeout=5))
                    late_handler = logging.StreamHandler(late_stream)
                    logger.addHandler(late_handler)
                    release_path.set()
                    worker.join(timeout=5)
                    logger.error("password=%s", marker)

                self.assertFalse(worker.is_alive())
                self.assertIn(late_handler, logger.handlers)
                self.assertNotIn(marker, late_stream.getvalue())
                self.assertIn("[REDACTED]", late_stream.getvalue())
            finally:
                release_path.set()
                worker.join(timeout=5)
                self._reset_logger(logger)

    def test_handler_list_mutators_harden_late_handlers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            augmented_stream = io.StringIO()
            sliced_stream = io.StringIO()

            logger = logging.getLogger("metroliza_test_logging_handler_mutators")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.handlers += [logging.StreamHandler(augmented_stream)]
                    logger.handlers[0:0] = [logging.StreamHandler(sliced_stream)]
                    logger.error("password=%s", marker)

                for output in (augmented_stream.getvalue(), sliced_stream.getvalue()):
                    self.assertNotIn(marker, output)
                    self.assertIn("[REDACTED]", output)
            finally:
                self._reset_logger(logger)

    def test_last_resort_redacts_during_configuration_transition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            path_requested = threading.Event()
            release_path = threading.Event()
            fallback_output = io.StringIO()

            def paused_home():
                path_requested.set()
                release_path.wait(timeout=5)
                return fake_home

            logger = logging.getLogger("metroliza_test_logging_transition_fallback")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            worker = threading.Thread(target=ensure_application_logging)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", side_effect=paused_home
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", fallback_output):
                    worker.start()
                    self.assertTrue(path_requested.wait(timeout=5))
                    logger.error("event-id=transition password=%s", marker)
                    release_path.set()
                    worker.join(timeout=5)

                self.assertFalse(worker.is_alive())
                self.assertNotIn(marker, fallback_output.getvalue())
                self.assertIn("event-id=transition", fallback_output.getvalue())
                self.assertIn("[REDACTED]", fallback_output.getvalue())
            finally:
                release_path.set()
                worker.join(timeout=5)
                self._reset_logger(logger)

    def test_last_resort_remains_redacting_after_all_handlers_are_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            fallback_output = io.StringIO()

            logger = logging.getLogger("metroliza_test_logging_post_remove_fallback")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch("sys.stderr", fallback_output):
                    ensure_application_logging(level=logging.INFO)
                    for handler in list(logger.handlers):
                        logger.removeHandler(handler)
                        handler.close()
                    logger.error("event-id=post-remove password=%s", marker)

                self.assertNotIn(marker, fallback_output.getvalue())
                self.assertIn("event-id=post-remove", fallback_output.getvalue())
                self.assertIn("[REDACTED]", fallback_output.getvalue())
            finally:
                self._reset_logger(logger)

    def test_reconfiguration_sanitizes_preexisting_memory_handler_buffer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            target_stream = io.StringIO()

            logger = logging.getLogger("metroliza_test_logging_memory_buffer")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            target_handler = logging.StreamHandler(target_stream)

            class DequeMemoryHandler(logging.handlers.MemoryHandler):
                def __init__(self):
                    super().__init__(
                        capacity=10,
                        flushLevel=logging.CRITICAL + 10,
                        target=target_handler,
                        flushOnClose=False,
                    )
                    self.buffer = deque()
                    self.buffer_alias = self.buffer

            memory_handler = DequeMemoryHandler()
            logger.addHandler(memory_handler)
            logger.error("password=%s", marker)

            class CustomBufferedRecord(logging.LogRecord):
                pass

            memory_handler.handle(
                CustomBufferedRecord(
                    logger.name,
                    logging.ERROR,
                    __file__,
                    1,
                    "custom buffered diagnostic password=%s",
                    (marker,),
                    None,
                )
            )

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    self.assertIs(memory_handler.buffer, memory_handler.buffer_alias)
                    for buffered_record in memory_handler.buffer_alias:
                        target_handler.handle(buffered_record)
                    memory_handler.buffer_alias.clear()

                self.assertIn(memory_handler, logger.handlers)
                self.assertIsInstance(memory_handler.buffer, deque)
                self.assertNotIn(marker, target_stream.getvalue())
                self.assertIn("[REDACTED]", target_stream.getvalue())
                self.assertIn("custom buffered diagnostic", target_stream.getvalue())
            finally:
                self._reset_logger(logger)
                target_handler.close()

    def test_reconfiguration_scrubs_list_subclass_buffer_alias_in_place(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            target_stream = io.StringIO()
            target_handler = logging.StreamHandler(target_stream)

            class BufferList(list):
                pass

            logger = logging.getLogger("metroliza_test_logging_list_buffer_alias")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            memory_handler = logging.handlers.MemoryHandler(
                capacity=10,
                flushLevel=logging.CRITICAL + 10,
                target=target_handler,
                flushOnClose=False,
            )
            memory_handler.buffer = BufferList()
            buffer_alias = memory_handler.buffer
            logger.addHandler(memory_handler)
            logger.error("password=%s", marker)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    self.assertIs(memory_handler.buffer, buffer_alias)
                    for buffered_record in buffer_alias:
                        target_handler.handle(buffered_record)
                    buffer_alias.clear()

                self.assertNotIn(marker, target_stream.getvalue())
                self.assertIn("[REDACTED]", target_stream.getvalue())
            finally:
                self._reset_logger(logger)
                target_handler.close()

    def test_memory_handler_targets_are_hardened_initially_and_after_set_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(2)]
            initial_stream = io.StringIO()
            late_stream = io.StringIO()
            initial_target = logging.StreamHandler(initial_stream)
            late_target = logging.StreamHandler(late_stream)
            initial_formatter = logging.Formatter("INITIAL|password=%(message)s")
            late_formatter = logging.Formatter("LATE|password=%(message)s")
            initial_target.setFormatter(initial_formatter)
            late_target.setFormatter(late_formatter)

            logger = logging.getLogger("metroliza_test_logging_memory_targets")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            memory_handler = logging.handlers.MemoryHandler(
                capacity=10,
                flushLevel=logging.CRITICAL + 10,
                target=initial_target,
                flushOnClose=False,
            )
            logger.addHandler(memory_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("initial target event password=%s", markers[0])
                    memory_handler.flush()
                    memory_handler.setTarget(late_target)
                    logger.error("late target event password=%s", markers[1])
                    memory_handler.flush()

                self.assertIs(initial_target.formatter, initial_formatter)
                self.assertIs(late_target.formatter, late_formatter)
                self.assertNotIn(markers[0], initial_stream.getvalue())
                self.assertNotIn(markers[1], late_stream.getvalue())
                self.assertIn(
                    "INITIAL|password=[REDACTED]",
                    initial_stream.getvalue(),
                )
                self.assertIn(
                    "LATE|password=[REDACTED]",
                    late_stream.getvalue(),
                )
            finally:
                self._reset_logger(logger)
                initial_target.close()
                late_target.close()

    def test_oversized_memory_buffers_are_bounded_and_scrubbed_in_place(self):
        class BufferList(list):
            pass

        class BufferDeque(deque):
            pass

        for buffer_type in (BufferList, BufferDeque):
            with self.subTest(buffer_type=buffer_type.__name__), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                fake_home = root / "home"
                fake_home.mkdir()
                fake_cwd = root / "project"
                fake_cwd.mkdir()
                marker = f"generated-{uuid.uuid4().hex}"
                target_stream = io.StringIO()
                target_handler = logging.StreamHandler(target_stream)
                record = logging.LogRecord(
                    "synthetic",
                    logging.ERROR,
                    __file__,
                    1,
                    "password=%s",
                    (marker,),
                    None,
                )

                logger = logging.getLogger(
                    f"metroliza_test_logging_bounded_buffer_{buffer_type.__name__}"
                )
                self._reset_logger(logger)
                logger.setLevel(logging.INFO)
                logger.propagate = False
                memory_handler = logging.handlers.MemoryHandler(
                    capacity=4096,
                    flushLevel=logging.CRITICAL + 10,
                    target=target_handler,
                    flushOnClose=False,
                )
                memory_handler.buffer = buffer_type([record] * 2048)
                buffer_alias = memory_handler.buffer
                logger.addHandler(memory_handler)

                try:
                    started = time.perf_counter()
                    with patch(
                        "metroliza.shared.logging_utils.logging.getLogger",
                        return_value=logger,
                    ), patch(
                        "metroliza.shared.logging_utils.Path.home",
                        return_value=fake_home,
                    ), patch(
                        "metroliza.shared.logging_utils.Path.cwd",
                        return_value=fake_cwd,
                    ):
                        ensure_application_logging(level=logging.INFO)
                    elapsed = time.perf_counter() - started

                    self.assertIs(memory_handler.buffer, buffer_alias)
                    self.assertEqual(len(buffer_alias), 129)
                    self.assertLess(elapsed, 1.0)
                    memory_handler.flush()
                    output = target_stream.getvalue()
                    self.assertNotIn(marker, output)
                    self.assertIn("buffered_records_truncated=present", output)
                finally:
                    self._reset_logger(logger)
                    target_handler.close()

    def test_unsupported_buffer_objects_are_replaced_without_running_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            calls: list[str] = []

            class HostileBuffer:
                def clear(self):
                    calls.append("clear")
                    raise KeyboardInterrupt(marker)

            logger = logging.getLogger("metroliza_test_unsupported_buffer")
            self._reset_logger(logger)
            logger.propagate = False
            handler = logging.handlers.BufferingHandler(capacity=10)
            handler.buffer = HostileBuffer()
            logger.addHandler(handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)

                self.assertEqual(calls, [])
                self.assertIs(type(handler.buffer), list)
                self.assertEqual(len(handler.buffer), 1)
                self.assertNotIn(marker, handler.buffer[0].getMessage())
            finally:
                self._reset_logger(logger)

    def test_setup_replaces_duplicate_unsafe_managed_handlers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            home_log_path = fake_home / ".metroliza" / "metroliza.log"
            home_log_path.parent.mkdir(parents=True)
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_duplicate_handlers")
            self._reset_logger(logger)
            logger.propagate = False
            for _ in range(2):
                handler = logging.handlers.RotatingFileHandler(
                    home_log_path,
                    maxBytes=10 * 1024 * 1024,
                    backupCount=7,
                    encoding="utf-8",
                )
                setattr(handler, "_metroliza_file_handler", True)
                logger.addHandler(handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("event-id=deduplicated password=%s", marker)

                matching_handlers = [
                    handler
                    for handler in logger.handlers
                    if isinstance(handler, logging.FileHandler)
                    and Path(handler.baseFilename).resolve() == home_log_path.resolve()
                ]
                home_log = home_log_path.read_text(encoding="utf-8")
                self.assertEqual(len(matching_handlers), 1)
                self.assertEqual(home_log.count("event-id=deduplicated"), 1)
                self.assertNotIn(marker, home_log)
            finally:
                self._reset_logger(logger)

    def test_handler_replacement_redacts_emit_already_past_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            home_log_path = fake_home / ".metroliza" / "metroliza.log"
            home_log_path.parent.mkdir(parents=True)
            marker = f"generated-{uuid.uuid4().hex}"
            filter_entered = threading.Event()
            release_filter = threading.Event()

            class PausingFilter(logging.Filter):
                def filter(self, _record):
                    filter_entered.set()
                    return release_filter.wait(timeout=5)

            logger = logging.getLogger("metroliza_test_logging_replacement_race")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            legacy_handler = logging.handlers.RotatingFileHandler(
                home_log_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=7,
                encoding="utf-8",
            )
            legacy_handler.setFormatter(logging.Formatter("%(message)s"))
            legacy_handler.addFilter(PausingFilter())
            setattr(legacy_handler, "_metroliza_file_handler", True)
            logger.addHandler(legacy_handler)
            worker = threading.Thread(
                target=logger.error,
                args=("event-id=reconfigure password=%s", marker),
            )

            try:
                worker.start()
                self.assertTrue(filter_entered.wait(timeout=5))
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)
                release_filter.set()
                worker.join(timeout=5)

                self.assertFalse(worker.is_alive())
                home_log = home_log_path.read_text(encoding="utf-8")
                self.assertNotIn(marker, home_log)
                self.assertIn("event-id=reconfigure", home_log)
            finally:
                release_filter.set()
                worker.join(timeout=5)
                self._reset_logger(logger)

    def test_safe_console_fallback_prevents_raw_last_resort_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_cwd = root / "project"
            console = io.StringIO()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_safe_fallback")
            self._reset_logger(logger)
            logger.propagate = False

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": ""}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
                ), patch(
                    "metroliza.shared.logging_utils._SafeRotatingFileHandler",
                    side_effect=OSError("synthetic local file failure"),
                ), patch("sys.stderr", console):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                fallback_handlers = [
                    handler
                    for handler in logger.handlers
                    if getattr(handler, "_metroliza_safe_fallback_handler", False)
                ]
                self.assertEqual(len(fallback_handlers), 1)
                self.assertNotIn(marker, console.getvalue())
                self.assertIn("[REDACTED]", console.getvalue())
            finally:
                self._reset_logger(logger)

    def test_unavailable_cwd_does_not_bypass_home_sink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_home = Path(tmpdir) / "home"
            fake_home.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_unavailable_cwd")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    side_effect=FileNotFoundError("synthetic removed cwd"),
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(marker, home_log)
                self.assertIn("[REDACTED]", home_log)
            finally:
                self._reset_logger(logger)

    def test_path_resolution_failure_uses_safe_console_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            console = io.StringIO()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_resolve_fallback")
            self._reset_logger(logger)
            logger.propagate = False

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": ""}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=root / "home"
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=root / "project"
                ), patch(
                    "metroliza.shared.logging_utils.Path.resolve",
                    side_effect=OSError("synthetic local resolution failure"),
                ), patch("sys.stderr", console):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                self.assertNotIn(marker, console.getvalue())
                self.assertIn("[REDACTED]", console.getvalue())
            finally:
                self._reset_logger(logger)

    def test_unresolved_managed_file_handler_is_retired(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_log_path = root / "legacy" / "metroliza.log"
            legacy_log_path.parent.mkdir()
            console = io.StringIO()
            marker = f"generated-{uuid.uuid4().hex}"

            logger = logging.getLogger("metroliza_test_logging_unresolved_managed")
            self._reset_logger(logger)
            logger.propagate = False
            legacy_handler = logging.handlers.RotatingFileHandler(
                legacy_log_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=7,
                encoding="utf-8",
            )
            legacy_handler.setFormatter(logging.Formatter("%(message)s"))
            setattr(legacy_handler, "_metroliza_file_handler", True)
            logger.addHandler(legacy_handler)

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": ""}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=root / "home"
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd", return_value=root / "project"
                ), patch(
                    "metroliza.shared.logging_utils.Path.resolve",
                    side_effect=OSError("synthetic local resolution failure"),
                ), patch("sys.stderr", console):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                self.assertNotIn(legacy_handler, logger.handlers)
                self.assertNotIn(marker, console.getvalue())
                self.assertIn("[REDACTED]", console.getvalue())
            finally:
                self._reset_logger(logger)

    def test_managed_redaction_is_thread_safe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            markers = [f"generated-{uuid.uuid4().hex}" for _ in range(12)]

            logger = logging.getLogger("metroliza_test_logging_concurrent_redaction")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
                ), patch(
                    "metroliza.shared.logging_utils.Path.home", return_value=fake_home
                ), patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd):
                    ensure_application_logging(level=logging.INFO)

                workers = [
                    threading.Thread(
                        target=logger.error,
                        args=("event-id=[%d] token=%s", index, marker),
                    )
                    for index, marker in enumerate(markers)
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                for index, marker in enumerate(markers):
                    self.assertNotIn(marker, home_log)
                    self.assertEqual(home_log.count(f"event-id=[{index}]"), 1)
            finally:
                self._reset_logger(logger)

    def test_percent_formatting_is_bounded_and_preserves_safe_dynamic_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            captured: list[str] = []

            class CapturingHandler(logging.Handler):
                def emit(self, record):
                    captured.append(record.getMessage())

            logger = logging.getLogger("metroliza_test_bounded_percent_format")
            self._reset_logger(logger)
            logger.propagate = False
            logger.addHandler(CapturingHandler())

            try:
                started = time.perf_counter()
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("width=%*s", 5, "x")
                    logger.info("precision=%.*s", 2, "abc")
                    logger.info("float=%*.*f", 8, 2, 1.25)
                    logger.info("bool-width-true=%*s", True, "x")
                    logger.info("bool-width-false=%*s", False, "x")
                    logger.info("bool-precision-true=%.*s", True, "abc")
                    logger.info("bool-precision-false=%.*s", False, "abc")
                    logger.info("tuple0=%s", ())
                    logger.info("tuple1=%s", (1,))
                    logger.info("tuple2=%s", (1, 2))
                    logger.info("map=%(value)s", {"value": (1, 2)})
                    logger.info(
                        "balanced=%(request(id))s",
                        {"request(id)": "42"},
                    )
                    logger.info(
                        "nested=%(a(b(c)))s",
                        {"a(b(c))": "deep"},
                    )
                    logger.info("empty=%()s", {"": "value"})
                    logger.error("password=%100000000s", marker)
                    logger.error("password=%*s", 100000000, marker)
                    logger.error("password=%.*s", 100000000, marker)
                elapsed = time.perf_counter() - started

                home_log = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                combined = f"{home_log}\n{' '.join(captured)}"
                self.assertNotIn(marker, combined)
                self.assertIn("width=    x", combined)
                self.assertIn("precision=ab", combined)
                self.assertIn("float=    1.25", combined)
                self.assertIn("bool-width-true=x", combined)
                self.assertIn("bool-width-false=x", combined)
                self.assertIn("bool-precision-true=a", combined)
                self.assertIn("bool-precision-false=", combined)
                self.assertIn("tuple0=()", combined)
                self.assertIn("tuple1=(1,)", combined)
                self.assertIn("tuple2=(1, 2)", combined)
                self.assertIn("map=(1, 2)", combined)
                self.assertIn("balanced=42", combined)
                self.assertIn("nested=deep", combined)
                self.assertIn("empty=value", combined)
                self.assertIn("format_error=present", combined)
                self.assertLess(elapsed, 1.0)
            finally:
                self._reset_logger(logger)

    def test_log_record_clone_bypasses_hostile_instance_dict_and_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            calls: list[str] = []

            class HostileKey:
                def __hash__(self):
                    return hash("missing-core-key")

                def __eq__(self, _other):
                    calls.append("key-equality")
                    return False

            class HostileRecord(logging.LogRecord):
                @property
                def __dict__(self):
                    calls.append("dict-property")
                    return {"msg": marker, "args": ()}

            logger = logging.getLogger("metroliza_test_hostile_record_dict")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    record = HostileRecord(
                        logger.name,
                        logging.ERROR,
                        __file__,
                        1,
                        "password=%s",
                        (marker,),
                        None,
                    )
                    values = logging.LogRecord.__dict__["__dict__"].__get__(
                        record,
                        type(record),
                    )
                    values[HostileKey()] = marker
                    calls.clear()
                    logger.handle(record)

                output = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(calls, [])
                self.assertNotIn(marker, output)
                self.assertIn("[REDACTED]", output)
            finally:
                self._reset_logger(logger)

    def test_unknown_object_class_hook_is_not_executed_or_misclassified(self):
        marker = f"generated-{uuid.uuid4().hex}"
        calls: list[str] = []

        class HostileObject:
            @property
            def __class__(self):
                calls.append("class-property")
                return Exception

            def __str__(self):
                calls.append("string-conversion")
                return marker

        output = redact_log_text(HostileObject())

        self.assertEqual(calls, [])
        self.assertNotIn(marker, output)
        self.assertIn("object_type=HostileObject", output)
        self.assertNotIn("exception_type=", output)

    def test_malformed_traceback_and_stack_values_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            calls: list[str] = []

            class HostileStack:
                def __str__(self):
                    calls.append("stack-string")
                    return marker

            logger = logging.getLogger("metroliza_test_malformed_traceback_stack")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    exception = RuntimeError(marker)
                    logger.error(
                        "synthetic traceback diagnostic",
                        exc_info=(RuntimeError, exception, object()),
                    )
                    record = logger.makeRecord(
                        logger.name,
                        logging.ERROR,
                        __file__,
                        1,
                        "synthetic stack diagnostic",
                        (),
                        None,
                    )
                    record.stack_info = HostileStack()
                    logger.handle(record)

                output = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(calls, [])
                self.assertNotIn(marker, output)
                self.assertIn("traceback=unknown", output)
                self.assertIn("traceback_unknown=yes", output)
                self.assertIn("stack=unknown", output)
            finally:
                self._reset_logger(logger)

    def test_oversized_stack_summary_does_not_split_or_render_stack_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            logger = logging.getLogger("metroliza_test_oversized_stack")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    record = logger.makeRecord(
                        logger.name,
                        logging.ERROR,
                        __file__,
                        1,
                        "bounded stack diagnostic",
                        (),
                        None,
                    )
                    record.stack_info = f"source={marker}" + "\n" * 1000000
                    started = time.perf_counter()
                    logger.handle(record)
                    elapsed = time.perf_counter() - started

                output = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertNotIn(marker, output)
                self.assertIn("stack_lines=unknown", output)
                self.assertIn("stack_truncated=yes", output)
                self.assertLess(elapsed, 1.0)
            finally:
                self._reset_logger(logger)

    def test_existing_handlers_are_detached_before_hardening(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            gate_entered = threading.Event()
            release_gate = threading.Event()
            captured: list[str] = []
            worker_errors: list[BaseException] = []
            fallback_stream = io.StringIO()

            class GateLock:
                def acquire(self):
                    gate_entered.set()
                    release_gate.wait(timeout=5)
                    return True

                def release(self):
                    return None

            class DirectHandler(logging.Handler):
                def handle(self, record):
                    captured.append(record.getMessage())
                    return True

                def emit(self, record):
                    raise AssertionError("direct handler does not emit")

            logger = logging.getLogger("metroliza_test_atomic_handler_hardening")
            self._reset_logger(logger)
            logger.setLevel(logging.INFO)
            logger.propagate = False
            direct_handler = DirectHandler()
            direct_handler.lock = GateLock()
            logger.addHandler(direct_handler)
            original_last_resort = logging.lastResort
            logging.lastResort = logging.StreamHandler(fallback_stream)

            def configure_logging():
                try:
                    ensure_application_logging(level=logging.INFO)
                except BaseException as error:
                    worker_errors.append(error)

            worker = threading.Thread(target=configure_logging)
            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    worker.start()
                    self.assertTrue(gate_entered.wait(timeout=5))
                    logger.error("password=%s", marker)
                    release_gate.set()
                    worker.join(timeout=5)
                    logger.error("post-setup password=%s", marker)

                self.assertFalse(worker.is_alive())
                self.assertEqual(worker_errors, [])
                self.assertNotIn(marker, "".join(captured))
                self.assertNotIn(marker, fallback_stream.getvalue())
                self.assertIn("[REDACTED]", fallback_stream.getvalue())
                self.assertIn("post-setup password=[REDACTED]", "".join(captured))
            finally:
                release_gate.set()
                worker.join(timeout=5)
                logging.lastResort = original_last_resort
                self._reset_logger(logger)

    def test_handler_removed_during_hardening_is_not_reattached(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            gate_entered = threading.Event()
            release_gate = threading.Event()
            worker_errors: list[BaseException] = []

            class GateLock:
                def acquire(self):
                    gate_entered.set()
                    release_gate.wait(timeout=5)
                    return True

                def release(self):
                    return None

            logger = logging.getLogger("metroliza_test_remove_during_hardening")
            self._reset_logger(logger)
            logger.propagate = False
            handler = logging.StreamHandler(io.StringIO())
            handler.lock = GateLock()
            logger.addHandler(handler)
            second_handler = logging.NullHandler()
            logger.addHandler(second_handler)

            def configure_logging():
                try:
                    ensure_application_logging(level=logging.INFO)
                except BaseException as error:
                    worker_errors.append(error)

            worker = threading.Thread(target=configure_logging)
            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    worker.start()
                    self.assertTrue(gate_entered.wait(timeout=5))
                    self.assertIn(handler, logger.handlers)
                    handlers = logger.handlers.copy()
                    handlers.remove(handler)
                    logger.handlers = handlers
                    logger.removeHandler(second_handler)
                    release_gate.set()
                    worker.join(timeout=5)

                self.assertFalse(worker.is_alive())
                self.assertEqual(worker_errors, [])
                self.assertNotIn(handler, logger.handlers)
                self.assertNotIn(second_handler, logger.handlers)
            finally:
                release_gate.set()
                worker.join(timeout=5)
                handler.lock = threading.RLock()
                handler.close()
                second_handler.close()
                self._reset_logger(logger)

    def test_discarded_handler_snapshot_does_not_remove_live_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            gate_entered = threading.Event()
            release_gate = threading.Event()
            worker_errors: list[BaseException] = []

            class GateLock:
                def acquire(self):
                    gate_entered.set()
                    release_gate.wait(timeout=5)
                    return True

                def release(self):
                    return None

            logger = logging.getLogger("metroliza_test_discarded_handler_snapshot")
            self._reset_logger(logger)
            logger.propagate = False
            handler = logging.StreamHandler(io.StringIO())
            handler.lock = GateLock()
            logger.addHandler(handler)

            def configure_logging():
                try:
                    ensure_application_logging(level=logging.INFO)
                except BaseException as error:
                    worker_errors.append(error)

            worker = threading.Thread(target=configure_logging)
            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    worker.start()
                    self.assertTrue(gate_entered.wait(timeout=5))
                    snapshot = logger.handlers.copy()
                    snapshot.remove(handler)
                    self.assertIn(handler, logger.handlers)
                    release_gate.set()
                    worker.join(timeout=5)

                self.assertFalse(worker.is_alive())
                self.assertEqual(worker_errors, [])
                self.assertIn(handler, logger.handlers)
            finally:
                release_gate.set()
                worker.join(timeout=5)
                handler.lock = threading.RLock()
                self._reset_logger(logger)

    def test_repeated_setup_preserves_handler_boundary_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            logger = logging.getLogger("metroliza_test_handler_boundary_alias")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    handler_alias = logger.handlers
                    ensure_application_logging(level=logging.INFO)

                self.assertIs(logger.handlers, handler_alias)
                retained_handler = handler_alias[0]
                independent_copy = handler_alias.copy()
                independent_copy.remove(retained_handler)
                self.assertIn(retained_handler, handler_alias)
                handler_alias.remove(retained_handler)
                try:
                    self.assertNotIn(retained_handler, logger.handlers)
                finally:
                    retained_handler.close()
            finally:
                self._reset_logger(logger)

    def test_hostile_handle_error_callable_is_not_introspected_during_setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            calls: list[str] = []

            class ErrorPolicy:
                def __call__(self, _record):
                    calls.append("called")

                def __getattribute__(self, name):
                    if name == "__func__":
                        calls.append("introspected")
                        raise RuntimeError("synthetic introspection failure")
                    return object.__getattribute__(self, name)

            logger = logging.getLogger("metroliza_test_hostile_error_policy")
            self._reset_logger(logger)
            logger.propagate = False
            handler = logging.StreamHandler(io.StringIO())
            handler.handleError = ErrorPolicy()
            logger.addHandler(handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)

                self.assertEqual(calls, [])
            finally:
                self._reset_logger(logger)

    def test_record_argument_clone_avoids_hostile_mapping_metaclass_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            calls: list[str] = []
            metaclass_hooks_armed = False

            class HostileMappingMeta(ABCMeta):
                def __getattribute__(cls, name):
                    if metaclass_hooks_armed and name in {
                        "_abc_impl",
                        "__subclasshook__",
                        "__subclasses__",
                    }:
                        calls.append(name)
                        raise RuntimeError("synthetic metaclass hook")
                    return ABCMeta.__getattribute__(cls, name)

            class HostileArguments(
                AbstractMapping,
                metaclass=HostileMappingMeta,
            ):
                def __getitem__(self, key):
                    return {"password": marker}[key]

                def __iter__(self):
                    return iter(("password",))

                def __len__(self):
                    return 1

            arguments = HostileArguments()
            calls.clear()
            logger = logging.getLogger("metroliza_test_hostile_mapping_metaclass")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    record = logging.LogRecord(
                        logger.name,
                        logging.ERROR,
                        "",
                        0,
                        "payload=%s",
                        (),
                        None,
                    )
                    record.args = arguments
                    metaclass_hooks_armed = True
                    try:
                        logger.handle(record)
                    finally:
                        metaclass_hooks_armed = False

                output = (fake_home / ".metroliza" / "metroliza.log").read_text(
                    encoding="utf-8"
                )
                self.assertEqual(calls, [])
                self.assertNotIn(marker, output)
                self.assertIn("payload=%s", output)
            finally:
                self._reset_logger(logger)

    def test_handler_setup_avoids_hostile_metaclass_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            calls: list[str] = []

            class HostileHandlerMeta(type):
                def __getattribute__(cls, name):
                    if name in {"handleError", "handle", "__mro__", "__dict__"}:
                        calls.append(name)
                        raise RuntimeError("synthetic metaclass hook")
                    return type.__getattribute__(cls, name)

            class HostileHandler(logging.Handler, metaclass=HostileHandlerMeta):
                def emit(self, _record):
                    return None

            handler = HostileHandler()
            calls.clear()
            logger = logging.getLogger("metroliza_test_hostile_handler_metaclass")
            self._reset_logger(logger)
            logger.propagate = False
            logger.addHandler(handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)

                self.assertEqual(calls, [])
            finally:
                self._reset_logger(logger)

    def test_exact_null_handler_instance_override_receives_safe_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            captured: list[str] = []
            logger = logging.getLogger("metroliza_test_null_handler_override")
            self._reset_logger(logger)
            logger.propagate = False
            handler = logging.NullHandler()
            handler.handle = lambda record: captured.append(record.getMessage()) or True
            logger.addHandler(handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.error("password=%s", marker)

                self.assertNotIn(marker, "".join(captured))
                self.assertIn("[REDACTED]", "".join(captured))
            finally:
                self._reset_logger(logger)

    def test_existing_exact_console_handler_preserves_identity_and_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            stream = io.StringIO()
            observations: list[str] = []

            class ObservingFilter(logging.Filter):
                def filter(self, record):
                    observations.append(record.getMessage())
                    return True

            logger = logging.getLogger("metroliza_test_existing_console_identity")
            self._reset_logger(logger)
            logger.propagate = False
            console_handler = logging.StreamHandler(stream)
            console_handler.addFilter(ObservingFilter())
            setattr(console_handler, "_metroliza_console_handler", True)
            logger.addHandler(console_handler)

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("safe console message")

                self.assertIn(console_handler, logger.handlers)
                self.assertEqual(observations, ["safe console message"])
                self.assertIn("safe console message", stream.getvalue())
            finally:
                self._reset_logger(logger)

    def test_existing_exact_console_handler_preserves_instance_emit_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            marker = f"generated-{uuid.uuid4().hex}"
            captured: list[str] = []
            logger = logging.getLogger("metroliza_test_exact_console_emit_override")
            self._reset_logger(logger)
            logger.propagate = False
            console_handler = logging.StreamHandler(io.StringIO())
            console_handler.emit = lambda record: captured.append(record.getMessage())
            setattr(console_handler, "_metroliza_console_handler", True)
            logger.addHandler(console_handler)

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("safe console message")
                    logger.error("password=%s", marker)

                self.assertIn(console_handler, logger.handlers)
                self.assertIn("safe console message", captured)
                self.assertNotIn(marker, "".join(captured))
                self.assertIn("password=[REDACTED]", captured)
            finally:
                self._reset_logger(logger)

    def test_existing_managed_console_subclass_preserves_identity_and_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            stream = io.StringIO()
            observations: list[str] = []

            class CustomConsoleHandler(logging.StreamHandler):
                pass

            class ObservingFilter(logging.Filter):
                def filter(self, record):
                    observations.append(record.getMessage())
                    return True

            logger = logging.getLogger("metroliza_test_console_subclass_identity")
            self._reset_logger(logger)
            logger.propagate = False
            console_handler = CustomConsoleHandler(stream)
            observing_filter = ObservingFilter()
            console_handler.addFilter(observing_filter)
            setattr(console_handler, "_metroliza_console_handler", True)
            logger.addHandler(console_handler)

            env = {"METROLIZA_CONSOLE_LOG_LEVEL": "INFO"}
            try:
                with patch.dict("os.environ", env, clear=False), patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("safe subclass console message")

                self.assertIn(console_handler, logger.handlers)
                self.assertIn(observing_filter, console_handler.filters)
                self.assertEqual(observations, ["safe subclass console message"])
                self.assertIn("safe subclass console message", stream.getvalue())
            finally:
                self._reset_logger(logger)

    def test_existing_managed_rotating_subclass_preserves_identity_and_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            home_log = fake_home / ".metroliza" / "metroliza.log"
            home_log.parent.mkdir(parents=True)
            observations: list[str] = []

            class CustomRotatingHandler(logging.handlers.RotatingFileHandler):
                pass

            class ObservingFilter(logging.Filter):
                def filter(self, record):
                    observations.append(record.getMessage())
                    return True

            logger = logging.getLogger("metroliza_test_rotating_subclass_identity")
            self._reset_logger(logger)
            logger.propagate = False
            file_handler = CustomRotatingHandler(
                home_log,
                maxBytes=10 * 1024 * 1024,
                backupCount=7,
                encoding="utf-8",
            )
            observing_filter = ObservingFilter()
            file_handler.addFilter(observing_filter)
            setattr(file_handler, "_metroliza_file_handler", True)
            logger.addHandler(file_handler)

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    logger.info("safe subclass file message")

                self.assertIn(file_handler, logger.handlers)
                self.assertIn(observing_filter, file_handler.filters)
                self.assertEqual(observations, ["safe subclass file message"])
                self.assertIn(
                    "safe subclass file message",
                    home_log.read_text(encoding="utf-8"),
                )
            finally:
                self._reset_logger(logger)

    def test_corrupt_rotating_limits_do_not_execute_equality_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            calls: list[str] = []

            class HostileLimit:
                def __eq__(self, _other):
                    calls.append("equality")
                    raise RuntimeError("synthetic equality failure")

            logger = logging.getLogger("metroliza_test_corrupt_rotation_limit")
            self._reset_logger(logger)
            logger.propagate = False

            try:
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                    file_handler = next(
                        handler
                        for handler in logger.handlers
                        if type(handler).__name__ == "_SafeRotatingFileHandler"
                    )
                    file_handler.__dict__["maxBytes"] = HostileLimit()
                    ensure_application_logging(level=logging.INFO)

                self.assertEqual(calls, [])
                self.assertNotIn(file_handler, logger.handlers)
            finally:
                self._reset_logger(logger)

    def test_buffer_sanitization_has_one_aggregate_text_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_home = root / "home"
            fake_home.mkdir()
            fake_cwd = root / "project"
            fake_cwd.mkdir()
            target_handler = logging.StreamHandler(io.StringIO())
            logger = logging.getLogger("metroliza_test_aggregate_buffer_budget")
            self._reset_logger(logger)
            logger.propagate = False
            memory_handler = logging.handlers.MemoryHandler(
                capacity=128,
                flushLevel=logging.CRITICAL + 10,
                target=target_handler,
                flushOnClose=False,
            )
            safe_near_pattern = ("api keyx: " * 7000)[:65000]
            record = logging.LogRecord(
                logger.name,
                logging.INFO,
                __file__,
                1,
                safe_near_pattern,
                (),
                None,
            )
            memory_handler.buffer = [record] * 64
            logger.addHandler(memory_handler)

            try:
                started = time.perf_counter()
                with patch(
                    "metroliza.shared.logging_utils.logging.getLogger",
                    return_value=logger,
                ), patch(
                    "metroliza.shared.logging_utils.Path.home",
                    return_value=fake_home,
                ), patch(
                    "metroliza.shared.logging_utils.Path.cwd",
                    return_value=fake_cwd,
                ):
                    ensure_application_logging(level=logging.INFO)
                elapsed = time.perf_counter() - started

                self.assertLessEqual(len(memory_handler.buffer), 3)
                self.assertIn(
                    "buffered_records_truncated=present",
                    memory_handler.buffer[-1].getMessage(),
                )
                self.assertLess(elapsed, 1.0)
            finally:
                self._reset_logger(logger)
                target_handler.close()


if __name__ == "__main__":
    unittest.main()
