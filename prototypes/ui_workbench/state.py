"""Synthetic-only state owner. No production imports or filesystem report access."""

from dataclasses import dataclass, replace
from enum import Enum

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class Recognition(str, Enum):
    RECOGNIZED = "Recognized"
    AMBIGUOUS = "Ambiguous"
    UNSUPPORTED = "Unsupported"
    UNREADABLE = "Unreadable"


class Destination(str, Enum):
    NEW = "No match"
    UNKNOWN = "Match · verify"
    COMPLETE = "Accepted complete"
    INCOMPLETE = "Incomplete graph"


class Outcome(str, Enum):
    IMPORTED = "Imported"
    REPAIRED = "Repaired"
    PRESENT = "Already present"
    REPAIR_NEEDED = "Needs repair approval"
    FAILED = "Failed"
    CHANGED = "Changed since review"
    CANCELLED = "Cancelled"


@dataclass(frozen=True)
class Report:
    identity: str
    name: str
    folder: str
    parser: str = "CMM PDF"
    recognition: Recognition = Recognition.RECOGNIZED
    destination: Destination = Destination.NEW
    same_source: bool = False
    stale: bool = False
    fail: bool = False
    drift_on_execute: bool = False
    revision: int = 1
    confidence: int = 97

    @property
    def eligibility(self):
        if self.stale:
            return "Refresh review"
        if self.recognition != Recognition.RECOGNIZED:
            return "Blocked · recognition"
        if self.same_source:
            return "Excluded · source copy"
        return {
            Destination.NEW: "Import new",
            Destination.UNKNOWN: "Verify only",
            Destination.COMPLETE: "Verify · preserve",
            Destination.INCOMPLETE: "Repair · approval needed",
        }[self.destination]

    @property
    def selectable(self):
        return not (self.stale or self.same_source) and self.recognition == Recognition.RECOGNIZED

    @property
    def fingerprint(self):
        return f"synthetic:{self.identity}:v{self.revision}"


SCENARIOS = ("Validation batch", "Five eligible reports", "Destination matches only",
             "Empty source", "Missing source", "10,000 synthetic reports")


def fixtures(scenario):
    if scenario in ("Empty source", "Missing source"):
        return ()
    count = 10000 if scenario == SCENARIOS[-1] else 5 if scenario == SCENARIOS[1] else 24
    if scenario == SCENARIOS[2]:
        return tuple(Report(f"match-{i}", f"inspection_{i + 1:03}.pdf", "Destination-only batch",
                            destination=d) for i, d in enumerate(
            (Destination.INCOMPLETE, Destination.COMPLETE, Destination.UNKNOWN)))
    rows = []
    for i in range(count):
        kind = i % 24 if count != 5 else 0
        row = Report(f"report-{i:05}", f"inspection_{i + 1:05}.pdf", f"Batch {i // 24 + 1:03} / Station {i % 3 + 1}",
                     parser="CSV profile" if i % 4 == 0 else "CMM PDF", confidence=96 + i % 4)
        if 15 <= kind <= 19:
            row = replace(row, destination=(Destination.UNKNOWN, Destination.INCOMPLETE,
                                            Destination.COMPLETE, Destination.COMPLETE, Destination.UNKNOWN)[kind - 15])
        if kind == 20:
            row = replace(row, recognition=Recognition.AMBIGUOUS, confidence=51)
        if kind == 21:
            row = replace(row, recognition=Recognition.UNSUPPORTED, confidence=0)
        if kind == 22:
            row = replace(row, recognition=Recognition.UNREADABLE, confidence=0)
        if kind == 23:
            row = replace(row, stale=True)
        if kind == 13:
            row = replace(row, same_source=True)
        if kind == 12:
            row = replace(row, fail=True)
        if kind == 11:
            row = replace(row, drift_on_execute=True)
        rows.append(row)
    return tuple(rows)


@dataclass(frozen=True)
class Context:
    workspace: str = "Validation lab"
    source: str = SCENARIOS[0]
    destination: str = "Comparison lab · simulated"
    metadata: str = "Fast · no OCR"
    version: int = 0


@dataclass(frozen=True)
class Plan:
    context: Context
    review_version: int
    reports: tuple[Report, ...]
    allow_repair: bool
    review_matches: int
    review_discovered: int


class Session(QObject):
    """Only owner of context, review, selection and one in-memory task."""

    changed = pyqtSignal()
    rows_changed = pyqtSignal()

    def __init__(self, parent=None, *, interval=300):
        super().__init__(parent)
        self.context = Context()
        self.reports = fixtures(self.context.source)
        self.selected = set()
        self.review_version = 0
        self.review_current = False
        self.reviewing = False
        self.running = False
        self.plan = None
        self.results = {}
        self.history = []
        self.accepted = set()
        self.drift = set()
        self.message = "Review the synthetic source before choosing a scope."
        self.timer = QTimer(self)
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self.step)
        self.review_timer = QTimer(self)
        self.review_timer.setSingleShot(True)
        self.review_timer.setInterval(450)
        self.review_timer.timeout.connect(self.finish_review)

    @property
    def busy(self):
        return self.running or self.reviewing

    def change_context(self, **fields):
        if self.busy:
            raise ValueError("The running plan is immutable. Cancel or wait before changing context.")
        if all(getattr(self.context, k) == v for k, v in fields.items()):
            return
        self.context = replace(self.context, **fields, version=self.context.version + 1)
        self.reports = fixtures(self.context.source)
        self.selected.clear()
        self.review_current = False
        self.drift.clear()
        self.message = "Context changed. Approval cleared; review this source and destination again."
        self.rows_changed.emit()
        self.changed.emit()

    def review(self):
        if self.busy:
            return
        self.reviewing = True
        self.review_current = False
        self.selected.clear()
        self.message = "Simulated review in progress · no report files or database accessed."
        self.review_timer.start()
        self.changed.emit()

    def finish_review(self):
        if not self.reviewing:
            return
        self.review_timer.stop()
        self.reviewing = False
        self.review_version += 1
        self.review_current = self.context.source != "Missing source"
        self.reports = tuple(replace(r, stale=False, revision=r.revision + int(r.stale),
                                    destination=Destination.COMPLETE if (self.context.destination, r.identity) in self.accepted else r.destination)
                             for r in self.reports)
        self.drift.clear()
        self.message = ("Source unavailable (simulated). Choose another fixture source."
                        if not self.review_current else "Review current · choose an explicit subset. No records selected automatically.")
        self.rows_changed.emit()
        self.changed.emit()

    def select(self, identity, selected):
        if self.busy or not self.review_current:
            return False
        row = next((r for r in self.reports if r.identity == identity), None)
        if not row or not row.selectable:
            return False
        if selected:
            self.selected.add(identity)
        else:
            self.selected.discard(identity)
        self.changed.emit()
        return True

    def select_visible(self, identities):
        if self.busy or not self.review_current:
            return
        allowed = {r.identity for r in self.reports if r.selectable}
        self.selected.update(set(identities) & allowed)
        self.changed.emit()

    def clear_selection(self):
        if not self.busy:
            self.selected.clear()
            self.changed.emit()

    def make_plan(self, allow_repair=False):
        if self.busy or not self.review_current or not self.selected:
            raise ValueError("Review current inputs and select at least one report.")
        chosen = tuple(r for r in self.reports if r.identity in self.selected)
        if any(not r.selectable for r in chosen):
            raise ValueError("Selection contains changed or ineligible reports. Refresh review.")
        return Plan(self.context, self.review_version, chosen, allow_repair,
                    sum(r.destination != Destination.NEW for r in self.reports), len(self.reports))

    def start(self, plan):
        if plan != self.make_plan(plan.allow_repair):
            raise ValueError("Scope or context changed after confirmation. Confirm again.")
        if self.plan is not None:
            self.history.append((self.plan, dict(self.results)))
        self.plan = plan
        self.results = {}
        self.running = True
        self.message = "Simulated import / verification running. Context and scope are locked."
        self.timer.start()
        self.changed.emit()

    def step(self):
        if not self.running:
            return
        row = next((r for r in self.plan.reports if r.identity not in self.results), None)
        if row is None:
            self.finish()
            return
        key = (self.plan.context.destination, row.identity)
        if row.identity in self.drift or row.drift_on_execute:
            outcome = Outcome.CHANGED
        elif row.fail:
            outcome = Outcome.FAILED
        elif key in self.accepted or row.destination == Destination.COMPLETE:
            outcome = Outcome.PRESENT
        elif row.destination == Destination.INCOMPLETE:
            outcome = Outcome.REPAIRED if self.plan.allow_repair else Outcome.REPAIR_NEEDED
        elif row.destination == Destination.UNKNOWN:
            # Deterministic synthetic verification discovers an incomplete graph.
            outcome = Outcome.REPAIRED if self.plan.allow_repair else Outcome.REPAIR_NEEDED
        else:
            outcome = Outcome.IMPORTED
        if outcome in (Outcome.IMPORTED, Outcome.REPAIRED, Outcome.PRESENT):
            self.accepted.add(key)
        self.results[row.identity] = outcome
        self.changed.emit()
        if len(self.results) == len(self.plan.reports):
            self.finish()

    def finish(self):
        self.timer.stop()
        self.running = False
        self.message = "Simulation finished. Review per-report outcomes; accepted complete reports were preserved."
        self.changed.emit()

    def cancel(self):
        if self.reviewing:
            self.review_timer.stop()
            self.reviewing = False
            self.review_current = False
            self.message = "Simulated review cancelled. Refresh review to approve a scope."
        elif self.running:
            self.timer.stop()
            for row in self.plan.reports:
                if row.identity not in self.results:
                    self.results[row.identity] = Outcome.CANCELLED
            self.running = False
            self.message = "Simulation cancelled. Completed per-report outcomes remain preserved."
        self.changed.emit()

    def simulate_drift(self, identity):
        if self.running:
            raise ValueError("Fixture inputs cannot change during execution.")
        self.drift.add(identity)
        self.reports = tuple(replace(r, stale=True) if r.identity == identity else r for r in self.reports)
        self.review_current = False
        self.selected.clear()
        self.message = "Synthetic source changed since review. Approval cleared."
        self.rows_changed.emit()
        self.changed.emit()
