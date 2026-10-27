"""Pytest configuration shared across the test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


expected_qt_platform = os.environ.get("METROLIZA_EXPECT_QT_PLATFORM", "").strip()
if expected_qt_platform:
    if not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = expected_qt_platform
elif os.environ.get("QT_QPA_PLATFORM") not in {"offscreen", "minimal"}:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

# A developer desktop's platform theme or style override (e.g. QT_QPA_PLATFORMTHEME=gtk3
# with a dark GTK theme) changes the default palette and makes colour and geometry
# assertions depend on the host. CI runners set neither, so tests run without them.
for _host_qt_appearance in ("QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE"):
    os.environ.pop(_host_qt_appearance, None)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- One QApplication per test process (#1119) ------------------------------------
#
# Many test modules create their QApplication in a module-scoped fixture
# (``QApplication.instance() or QApplication([])``). Releasing that fixture value
# at the end of a module destroys the QApplication, and the next module creates a
# second one in the same process. Qt/PyQt do not support that: after the first
# QApplication has been destroyed, PyQt stops invalidating the wrappers of
# C++-created QObjects (``QMainWindow.menuBar()``, ``QMenuBar.addMenu()``, ...)
# when the C++ object is deleted. ``sip.isdeleted()`` stays False for the dead
# QMenu/QMenuBar, their addresses are reused by new widgets, and a later
# ``findChildren()``/``topLevelWidgets()`` walk dereferences freed memory
# (SIGSEGV in ``QObject::property``, see issue #1119). The product creates exactly
# one QApplication (``metroliza.app.bootstrap``), so only the test process is
# affected. Keep the first QApplication alive until the interpreter exits.
# Tests that first create an application inside their body must request
# qapplication_session: the post-call hook cannot retain a dead local variable.
_RETAINED_QT_APPLICATIONS: list = []


def retain_qapplication() -> None:
    """Keep the process' QApplication alive after fixtures drop their reference."""
    widgets = sys.modules.get("PyQt6.QtWidgets")
    application_type = getattr(widgets, "QApplication", None)
    if getattr(application_type, "__module__", None) != "PyQt6.QtWidgets":
        return  # Qt not imported, or replaced by a lightweight test stub.
    application = application_type.instance()
    if application is not None:
        from metroliza.app.gc_policy import install

        install(application)
        if not any(application is kept for kept in _RETAINED_QT_APPLICATIONS):
            _RETAINED_QT_APPLICATIONS.append(application)


@pytest.fixture(scope="session")
def qapplication_session():
    """Own the application before tests with only test-local Qt references run."""
    widgets = pytest.importorskip("PyQt6.QtWidgets")
    application = widgets.QApplication.instance() or widgets.QApplication([])
    retain_qapplication()
    return application


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    yield
    retain_qapplication()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    retain_qapplication()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    yield
    # Fixture teardown may release the final references to widget cycles. Sweep
    # young objects now on the main thread, promoting older generations only
    # when due; a full collection after every test would stall large Qt suites.
    retain_qapplication()
    if _RETAINED_QT_APPLICATIONS:
        # Use the installed policy directly: a test may still have stubbed PyQt6 modules.
        policy = getattr(_RETAINED_QT_APPLICATIONS[0], "_metroliza_gc_policy", None)
        if policy is not None:
            import gc

            if gc.isenabled():
                gc.disable()
                pytest.fail(f"{item.nodeid} re-enabled automatic GC while the GUI GC policy is installed")
            policy.collect_due(force_young=True)
