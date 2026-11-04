"""The test process keeps one QApplication alive across test modules (#1119).

Several modules create their QApplication in a module-scoped fixture. Without
``tests/conftest.py::retain_qapplication`` the first module destroys it and the
next module creates a second one. After that PyQt no longer invalidates wrappers of
C++-created QObjects (``menuBar()``, ``addMenu()``) when Qt deletes them, so a stale
QMenu wrapper later aliases freed memory and ``findChildren()`` crashes with SIGSEGV.
Test-local owners instead request the session fixture before the body executes.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

FIRST_MODULE = '''
import pytest
from PyQt6.QtWidgets import QApplication
from tests.conftest import _RETAINED_QT_APPLICATIONS


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_first_module_owns_the_application(app):
    import gc
    assert QApplication.instance() is app
    assert any(app is kept for kept in _RETAINED_QT_APPLICATIONS)
    assert not gc.isenabled()
    assert app._metroliza_gc_policy.timer.isActive()
'''

LOCAL_MODULE = '''
import weakref

import pytest
from PyQt6.QtWidgets import QApplication
from tests.conftest import _RETAINED_QT_APPLICATIONS

pytestmark = pytest.mark.usefixtures("qapplication_session")

previous_application = None
previous_cycle = None
emergency_owner = []


@pytest.mark.parametrize("case", [0, 1])
def test_local_application_is_owned_before_the_body_returns(case):
    import gc
    global previous_application, previous_cycle
    if previous_application is not None:
        # Fail before creating a second application if ownership regresses.
        assert previous_application() is not None
        assert QApplication.instance() is previous_application()
        assert previous_cycle() is None, "young cycle survived per-test collection"
    app = QApplication.instance() or QApplication([])
    try:
        assert not gc.isenabled()
        assert app._metroliza_gc_policy.timer.isActive()
        assert any(app is kept for kept in _RETAINED_QT_APPLICATIONS), (
            "test-local QApplication has no process owner during the test body"
        )
        previous_application = weakref.ref(app)
        class Cycle:
            pass
        cycle = Cycle()
        cycle.self = cycle
        previous_cycle = weakref.ref(cycle)
    finally:
        # On failure, keep the first app alive so this regression cannot itself
        # recreate QApplication and leave unsafe Qt wrappers behind.
        if not any(app is kept for kept in _RETAINED_QT_APPLICATIONS):
            emergency_owner.append(app)
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


@pytest.mark.parametrize("first_module", [FIRST_MODULE, LOCAL_MODULE], ids=["module-fixture", "test-local"])
def test_qapplication_survives_module_scoped_fixtures_so_wrappers_stay_valid(tmp_path, first_module):
    first = tmp_path / "test_a_first_module.py"
    second = tmp_path / "test_b_second_module.py"
    first.write_text(textwrap.dedent(first_module))
    second.write_text(textwrap.dedent(SECOND_MODULE))
    environment = {
        key: value for key, value in os.environ.items() if key != "QT_QPA_PLATFORMTHEME"
    }
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), environment.get("PYTHONPATH", "")]
    )
    # Propagate the optional host safety plugin without requiring it in CI.
    safety_plugins = ["-p", "qt_app_keeper"] if "qt_app_keeper" in sys.modules else []

    completed = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-m",
            "pytest",
            *safety_plugins,
            "-q",
            "--maxfail=1",
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
    expected_count = 2 if first_module == FIRST_MODULE else 3
    assert f"{expected_count} passed" in completed.stdout


def test_diagnostic_qualification_owns_application_before_local_factory_returns(tmp_path):
    """Exercise the real first Qt cases without allowing unsafe app recreation."""
    plugin = tmp_path / "qualification_application_guard.py"
    plugin.write_text(textwrap.dedent('''
        import weakref

        import pytest

        previous = None

        @pytest.fixture(autouse=True)
        def guard_qualification_application(monkeypatch):
            from metroliza.app import bootstrap
            from tests.conftest import retain_qapplication

            original = bootstrap.get_or_create_qapplication

            def checked_factory(*args, **kwargs):
                global previous
                if previous is not None:
                    assert previous() is not None, "qualification destroyed its QApplication"
                app = original(*args, **kwargs)
                owned = getattr(app, "_metroliza_test_session_application", False)
                # Retain even a failing control before unwinding its local owner:
                # the regression must fail by assertion, never recreate Qt.
                retain_qapplication()
                previous = weakref.ref(app)
                assert owned, "qualification QApplication had no session owner during the test"
                return app

            monkeypatch.setattr(bootstrap, "get_or_create_qapplication", checked_factory)
    '''))
    environment = dict(os.environ)
    environment.pop("QT_QPA_PLATFORMTHEME", None)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), str(REPO_ROOT / "src"), str(REPO_ROOT)]
    )
    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-m", "pytest", "-q",
         "-p", "no:cacheprovider", "-o", "addopts=",
         "-p", "qualification_application_guard",
         "tests/test_diagnostic_qualification.py", "-k",
         "finish_barrier_accepts_file or finish_barrier_accepts_only_file_observed_before_deadline"],
        cwd=REPO_ROOT, env=environment, capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-2000:]
    assert "5 passed" in completed.stdout
