import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.logging_utils import ensure_application_logging


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


if __name__ == "__main__":
    unittest.main()
