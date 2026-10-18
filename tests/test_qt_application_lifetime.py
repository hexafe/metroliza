"""The test process keeps one QApplication alive across test modules (#1119).

Several modules create their QApplication in a module-scoped fixture. Without
``tests/conftest.py::retain_qapplication`` the first module destroys it and the
next module creates a second one. After that PyQt no longer invalidates wrappers of
C++-created QObjects (``menuBar()``, ``addMenu()``) when Qt deletes them, so a stale
QMenu wrapper later aliases freed memory and ``findChildren()`` crashes with SIGSEGV.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

REPO_ROOT = Path(__file__).resolve().parents[1]

FIRST_MODULE = '''
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_first_module_owns_the_application(app):
    assert QApplication.instance() is app
'''

SECOND_MODULE = '''
import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QApplication, QMainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_cxx_created_wrappers_are_invalidated_when_qt_deletes_them(app):
    window = QMainWindow()
    menu_bar = window.menuBar()
    menu = menu_bar.addMenu("Tools")
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(window)
    assert sip.isdeleted(menu_bar), "stale QMenuBar wrapper: QApplication was recreated"
    assert sip.isdeleted(menu), "stale QMenu wrapper: QApplication was recreated"
'''


def test_qapplication_survives_module_scoped_fixtures_so_wrappers_stay_valid(tmp_path):
    first = tmp_path / "test_a_first_module.py"
    second = tmp_path / "test_b_second_module.py"
    first.write_text(textwrap.dedent(FIRST_MODULE))
    second.write_text(textwrap.dedent(SECOND_MODULE))
    environment = {
        key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORMTHEME"
    }
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), environment.get("PYTHONPATH", "")]
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "-p",
            "tests.conftest",
            str(first),
            str(second),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    assert "2 passed" in completed.stdout
