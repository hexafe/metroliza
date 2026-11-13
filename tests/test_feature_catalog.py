from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re


FEATURE_CATALOG_PATH = Path("docs/project/feature_catalog.md")
EXPECTED_FEATURE_ISSUES = set(range(926, 958))
FEATURE_LINK_PATTERN = re.compile(
    r"\[#(?P<issue>\d+)\]\(https://github\.com/hexafe/metroliza/issues/(?P=issue)\)"
)
DEPENDENCY_LIST_PATTERN = re.compile(r"#\d+(?:, #\d+)*")
PHASE_RANGE_PATTERN = re.compile(r"(?P<first>[1-7])[–-](?P<last>[1-7])")
PHASE_LIST_PATTERN = re.compile(r"[1-7](?: and [1-7])*")
FEATURE_SECTION_START = "## 1. Workspace, import, data ownership, and curation"
FEATURE_SECTION_END = "## Cross-cutting engineering contracts"
EXPECTED_TABLE_HEADER = (
    "Capability",
    "Issue",
    "Current maturity",
    "Target phase",
    "Strict prerequisites",
)
EXPECTED_FEATURE_TABLES = 9
REQUIRED_FOUNDATION_EDGES = {
    (926, 945),
    (927, 928),
    (927, 929),
    (928, 951),
    (951, 950),
    (931, 939),
    (931, 940),
    (932, 933),
    (933, 934),
    (937, 946),
    (946, 947),
    (944, 928),
    (944, 929),
    (944, 930),
    (944, 938),
    (944, 940),
    (944, 941),
    (944, 943),
    (944, 945),
    (944, 949),
    (944, 950),
    (944, 953),
    (944, 955),
    (944, 957),
    (949, 943),
    (949, 948),
    (949, 953),
    (952, 939),
    (952, 940),
    (952, 941),
}


@dataclass(frozen=True)
class FeatureRow:
    issue: int
    dependencies: tuple[int, ...]
    phases: frozenset[int]
    line_number: int


def parse_target_phases(value: str, *, issue: int, line_number: int) -> frozenset[int]:
    range_match = PHASE_RANGE_PATTERN.fullmatch(value)
    if range_match:
        first = int(range_match.group("first"))
        last = int(range_match.group("last"))
        assert first <= last, f"#{issue} has reversed phase range on line {line_number}: {value}"
        return frozenset(range(first, last + 1))

    assert PHASE_LIST_PATTERN.fullmatch(value), (
        f"#{issue} has invalid target phase syntax on line {line_number}: {value}"
    )
    phases = tuple(int(part) for part in value.split(" and "))
    assert len(phases) == len(set(phases)), (
        f"#{issue} repeats a target phase on line {line_number}: {value}"
    )
    assert tuple(sorted(phases)) == phases, (
        f"#{issue} target phases are not ordered on line {line_number}: {value}"
    )
    return frozenset(phases)


def parse_feature_rows() -> list[FeatureRow]:
    rows: list[FeatureRow] = []
    catalog = FEATURE_CATALOG_PATH.read_text(encoding="utf-8")
    feature_sections = catalog[catalog.index(FEATURE_SECTION_START) : catalog.index(
        FEATURE_SECTION_END
    )]
    headers = 0

    start_line = catalog[: catalog.index(FEATURE_SECTION_START)].count("\n") + 1
    for line_number, line in enumerate(feature_sections.splitlines(), start=start_line):
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if len(cells) != 5:
            continue

        if tuple(cells) == EXPECTED_TABLE_HEADER or cells[0] == "Decision":
            assert tuple(cells[1:]) == EXPECTED_TABLE_HEADER[1:], (
                f"Invalid feature-table header on line {line_number}: {cells}"
            )
            headers += 1
            continue

        issue_match = FEATURE_LINK_PATTERN.fullmatch(cells[1])
        if issue_match is None:
            continue

        issue = int(issue_match.group("issue"))
        assert cells[0], f"#{issue} has an empty capability on line {line_number}"
        assert cells[2], f"#{issue} has an empty maturity on line {line_number}"
        assert DEPENDENCY_LIST_PATTERN.fullmatch(cells[4]), (
            f"#{issue} has invalid strict prerequisites on line {line_number}: {cells[4]}"
        )
        dependencies = tuple(int(value) for value in re.findall(r"#(\d+)", cells[4]))
        assert len(dependencies) == len(set(dependencies)), (
            f"#{issue} repeats a strict prerequisite on line {line_number}: {cells[4]}"
        )

        rows.append(
            FeatureRow(
                issue=issue,
                dependencies=dependencies,
                phases=parse_target_phases(cells[3], issue=issue, line_number=line_number),
                line_number=line_number,
            )
        )

    assert headers == EXPECTED_FEATURE_TABLES, (
        f"Expected {EXPECTED_FEATURE_TABLES} feature-table headers, found {headers}"
    )
    return rows


def test_feature_catalog_represents_every_product_issue_once() -> None:
    rows = parse_feature_rows()
    counts = Counter(row.issue for row in rows)

    assert set(counts) == EXPECTED_FEATURE_ISSUES, (
        "Feature catalog Issue inventory differs from #926–#957: "
        f"missing={sorted(EXPECTED_FEATURE_ISSUES - set(counts))}, "
        f"unexpected={sorted(set(counts) - EXPECTED_FEATURE_ISSUES)}"
    )
    duplicates = {issue: count for issue, count in counts.items() if count != 1}
    assert not duplicates, f"Feature catalog Issues must appear exactly once: {duplicates}"


def test_feature_catalog_strict_prerequisites_form_a_dag() -> None:
    rows = {row.issue: row for row in parse_feature_rows()}

    self_dependencies = {
        issue: row.line_number for issue, row in rows.items() if issue in row.dependencies
    }
    assert not self_dependencies, f"Feature catalog contains self-dependencies: {self_dependencies}"

    state: dict[int, int] = {}
    stack: list[int] = []

    def visit(issue: int) -> None:
        state[issue] = 1
        stack.append(issue)
        for dependency in rows[issue].dependencies:
            if dependency not in rows:
                continue
            if state.get(dependency) == 1:
                cycle_start = stack.index(dependency)
                cycle = stack[cycle_start:] + [dependency]
                rendered = " -> ".join(f"#{number}" for number in cycle)
                raise AssertionError(f"Feature catalog dependency cycle: {rendered}")
            if state.get(dependency, 0) == 0:
                visit(dependency)
        stack.pop()
        state[issue] = 2

    for issue in sorted(rows):
        if state.get(issue, 0) == 0:
            visit(issue)


def test_feature_catalog_target_phases_are_valid() -> None:
    rows = parse_feature_rows()

    invalid = {
        row.issue: sorted(row.phases)
        for row in rows
        if not row.phases or not row.phases <= set(range(1, 8))
    }
    assert not invalid, f"Feature catalog contains invalid target phases: {invalid}"


def test_feature_catalog_preserves_foundation_direction_and_phase_order() -> None:
    rows = {row.issue: row for row in parse_feature_rows()}
    missing_edges = {
        (prerequisite, consumer)
        for prerequisite, consumer in REQUIRED_FOUNDATION_EDGES
        if prerequisite not in rows[consumer].dependencies
    }
    assert not missing_edges, (
        "Feature catalog is missing normalized foundation edges: "
        f"{sorted(missing_edges)}"
    )

    phase_inversions = {
        (dependency, issue): (min(rows[dependency].phases), min(row.phases))
        for issue, row in rows.items()
        for dependency in row.dependencies
        if dependency in rows and min(rows[dependency].phases) > min(row.phases)
    }
    assert not phase_inversions, (
        "A strict prerequisite starts after its consumer: "
        f"{phase_inversions}"
    )


def test_feature_catalog_declares_strict_dependency_semantics() -> None:
    catalog = FEATURE_CATALOG_PATH.read_text(encoding="utf-8")

    assert "## Dependency semantics" in catalog
    assert "Principal dependencies" not in catalog
