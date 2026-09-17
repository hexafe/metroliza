"""Reproducible native offscreen screenshots and measured synthetic observations."""

import json
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import statistics
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from app import ScopeDialog, Workbench, install_safety_guard
from state import Session


def main():
    install_safety_guard()
    app = QApplication([])
    session = Session(interval=60000)
    window = Workbench(session)
    window.show()
    window.activateWindow()
    app.processEvents()
    output = Path(__file__).parent / "evidence"
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    if scale != "1":
        output = output / ("scale-" + scale.replace(".", ""))
    output.mkdir(exist_ok=True, parents=True)
    observations = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "qt": QT_VERSION_STR,
        "pyqt": PYQT_VERSION_STR,
        "platform": platform.platform(),
        "renderer": "native Qt Fusion / offscreen",
        "scale_factor": scale,
        "actual_device_pixel_ratio": window.devicePixelRatioF(),
        "geometry": [],
    }

    def capture(name):
        app.processEvents()
        QTest.qWait(40)
        path = output / (name + ".png")
        assert window.grab().save(str(path))

    session.review()
    session.finish_review()
    session.select("report-00000", True)
    session.select("report-00003", True)
    window.navigate(1)
    window.table.setCurrentIndex(window.proxy.index(0, 1))
    for mode in ("light", "dark"):
        window.set_theme(mode)
        for width, height in ((1024, 700), (1280, 800), (1600, 1000)):
            window.resize(width, height)
            app.processEvents()
            assert (window.width(), window.height()) == (width, height)
            reachable = {}
            for name in (
                "import_button",
                "review_button",
                "cancel_button",
                "search",
                "destination",
            ):
                widget = getattr(window, name)
                origin = widget.mapTo(window, widget.rect().topLeft())
                end = widget.mapTo(window, widget.rect().bottomRight())
                reachable[name] = window.rect().contains(origin) and window.rect().contains(end)
            observations["geometry"].append(
                {"theme": mode, "viewport": [width, height], "reachable": reachable}
            )
            assert all(reachable.values()), reachable
            capture(f"reports-{mode}-{width}x{height}")
    window.resize(1280, 800)
    window.navigate(0)
    capture("overview-dark")
    window.source.setCurrentText("Destination matches only")
    session.review()
    session.finish_review()
    window.navigate(1)
    window.select_visible()
    window.table.setCurrentIndex(window.proxy.index(0, 1))
    capture("destination-only")
    dialog = ScopeDialog(session, 0, window)
    dialog.show()
    dialog.activateWindow()
    app.processEvents()
    assert dialog.grab().save(str(output / "scope-confirmation.png"))
    dialog.close()
    window.activateWindow()
    session.start(session.make_plan(allow_repair=True))
    session.step()
    window.navigate(3)
    capture("task-survives-navigation")
    session.cancel()
    window.navigate(6)
    capture("partial-cancellation")

    for scenario, name in (("Empty source", "empty-source"), ("Missing source", "missing-source")):
        window.source.setCurrentText(scenario)
        session.review()
        session.finish_review()
        window.navigate(1)
        capture(name)
    window.source.setCurrentText("Five eligible reports")
    session.review()
    capture("pending-review")
    session.finish_review()
    session.select("report-00000", True)
    session.select("report-00003", True)
    session.start(session.make_plan())
    while session.running:
        session.step()
    window.navigate(6)
    capture("successful-subset")
    window.source.setCurrentText("Validation batch")
    session.review()
    session.finish_review()
    for identity in ("report-00000", "report-00011", "report-00012", "report-00014"):
        session.select(identity, True)
    session.start(session.make_plan())
    for _ in range(3):
        session.step()
    session.cancel()
    capture("partial-failure-changed-cancelled")

    window.source.setCurrentText("10,000 synthetic reports")
    started = time.perf_counter()
    session.review()
    session.finish_review()
    window.navigate(1)
    app.processEvents()
    observations["review_10000_ms"] = round((time.perf_counter() - started) * 1000, 2)
    timings = []
    for query in (
        "099",
        "Batch 200",
        "inspection",
        "00001",
        "",
        "Station 2",
        "050",
        "999",
        "",
        "Batch",
    ):
        started = time.perf_counter()
        window.search.setText(query)
        app.processEvents()
        timings.append(round((time.perf_counter() - started) * 1000, 2))
    observations["filter_10000_ms"] = {
        "samples": timings,
        "median": statistics.median(timings),
        "max": max(timings),
    }
    window.search.clear()
    started = time.perf_counter()
    window.table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    app.processEvents()
    observations["sort_10000_ms"] = round((time.perf_counter() - started) * 1000, 2)
    started = time.perf_counter()
    for position in (0, 500, 2000, 5000, 9999):
        window.table.scrollTo(window.proxy.index(position, 1))
        app.processEvents()
    observations["five_scroll_jumps_ms"] = round((time.perf_counter() - started) * 1000, 2)
    window.table.scrollToTop()
    capture("reports-10000")

    # The audit hook rejects these calls before any connection is established.
    import socket
    import sqlite3

    denied = []
    for name, action in (
        ("socket", socket.socket),
        ("sqlite", lambda: sqlite3.connect(":memory:")),
    ):
        try:
            action()
        except RuntimeError as exc:
            assert "Synthetic prototype forbids" in str(exc)
            denied.append(name)
        else:
            raise AssertionError(name + " was not denied")
    observations["blocked_connection_probes"] = denied
    observations["production_modules_loaded"] = [
        name for name in sys.modules if name.startswith(("metroliza", "modules."))
    ]
    assert not observations["production_modules_loaded"]
    (output / "observations.json").write_text(json.dumps(observations, indent=2) + "\n")
    print(json.dumps(observations, indent=2))
    window.close()


if __name__ == "__main__":
    main()
