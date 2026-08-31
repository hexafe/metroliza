from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTING_PATH = REPO_ROOT / "docs/engineering/codex-model-routing.md"
TASK_PACKET_PATH = REPO_ROOT / "docs/engineering/codex-task-packet-template.md"
PR_REPORT_PATH = REPO_ROOT / "docs/engineering/pr-routing-report-template.md"
WORKSPACE_PATH = REPO_ROOT / "docs/project/chatgpt_workspace.md"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"
POLICY_PATHS = (
    AGENTS_PATH,
    ROUTING_PATH,
    TASK_PACKET_PATH,
    PR_REPORT_PATH,
    WORKSPACE_PATH,
)

# This suite enforces structured authority, tables, sections, and required fields. Free-form
# semantic contradiction detection is intentionally outside its scope and remains a code-review
# responsibility.


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize(text: str) -> str:
    unstyled = re.sub(r"[`*_]", "", text.casefold())
    unhyphenated = re.sub(r"[-\N{EN DASH}\N{EM DASH}]", " ", unstyled)
    return " ".join(unhyphenated.split())


def section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if re.fullmatch(rf"(?P<marks>#+)\s+{re.escape(heading)}", line)
    )
    level = len(lines[start].split(maxsplit=1)[0])
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = re.match(r"^(?P<marks>#+)\s+", lines[index])
        if match and len(match.group("marks")) <= level:
            end = index
            break
    return "\n".join(lines[start:end])


def markdown_table(markdown: str, header: tuple[str, ...]) -> list[tuple[str, ...]]:
    lines = markdown.splitlines()
    expected_header = tuple(cell.casefold() for cell in header)
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip().casefold() for cell in line.strip("|").split("|"))
        if cells != expected_header:
            continue
        rows: list[tuple[str, ...]] = []
        for row in lines[index + 2 :]:
            if not row.startswith("|"):
                break
            rows.append(tuple(cell.strip() for cell in row.strip("|").split("|")))
        return rows
    raise AssertionError(f"Missing Markdown table with header: {header}")


def markdown_tables(markdown: str) -> list[tuple[tuple[str, ...], list[tuple[str, ...]]]]:
    lines = markdown.splitlines()
    tables: list[tuple[tuple[str, ...], list[tuple[str, ...]]]] = []
    for index, line in enumerate(lines[:-1]):
        if not line.startswith("|") or not lines[index + 1].startswith("|"):
            continue
        separators = tuple(cell.strip() for cell in lines[index + 1].strip("|").split("|"))
        if not separators or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators):
            continue
        header = tuple(normalize(cell) for cell in line.strip("|").split("|"))
        rows: list[tuple[str, ...]] = []
        for row in lines[index + 2 :]:
            if not row.startswith("|"):
                break
            rows.append(tuple(cell.strip() for cell in row.strip("|").split("|")))
        tables.append((header, rows))
    return tables


def numbered_items(markdown: str) -> list[str]:
    items: list[list[str]] = []
    for line in markdown.splitlines():
        match = re.match(r"^(?P<number>\d+)\.\s+(?P<text>.+)", line)
        if match:
            items.append([match.group("text")])
        elif items and (line.startswith("   ") or line.startswith("      ")):
            items[-1].append(line.strip())
    return [normalize(" ".join(item)) for item in items]


def assert_required_anchors(text: str, anchors: tuple[str, ...]) -> None:
    normalized = normalize(text)
    missing = [anchor for anchor in anchors if normalize(anchor) not in normalized]
    assert not missing, f"Missing required policy anchors: {missing}"


def assert_field_lines(text: str, fields: tuple[str, ...]) -> None:
    missing = [
        field
        for field in fields
        if re.search(rf"(?m)^\s*(?:-\s+)?{re.escape(field)}\s*:", text) is None
    ]
    assert not missing, f"Missing structural fields: {missing}"


def test_one_canonical_table_preserves_all_normal_routes() -> None:
    routing = read(ROUTING_PATH)
    rows = markdown_table(
        section(routing, "3. Canonical normal coordinator routes"),
        ("Work class", "Coordinator", "Reasoning", "Bounded-contract test"),
    )
    routes = {normalize(row[0]): (normalize(row[1]), normalize(row[2])) for row in rows}

    expected_routes = {
        "mechanical / recovery / inventory": ("gpt-5.6 luna", "medium"),
        "standard / bounded patch / test repair / audit finalization": (
            "gpt-5.6 terra",
            "high",
        ),
        "high / cross-layer / p0-p1 with an accepted contract": (
            "gpt-5.6 sol",
            "high",
        ),
    }
    assert routes == {
        normalize(work_class): (normalize(model), normalize(reasoning))
        for work_class, (model, reasoning) in expected_routes.items()
    }

    route_tables: list[tuple[Path, tuple[str, ...]]] = []
    for path in POLICY_PATHS:
        for header, _rows in markdown_tables(read(path)):
            if (
                "coordinator" in header
                and "reasoning" in header
                and any("class" in cell for cell in header)
            ):
                route_tables.append((path, header))
    assert route_tables == [
        (
            ROUTING_PATH,
            ("work class", "coordinator", "reasoning", "bounded contract test"),
        )
    ]


def test_ultra_requires_all_five_unweakened_admission_conditions() -> None:
    ultra = section(read(ROUTING_PATH), "4. Ultra admission contract")
    items = numbered_items(ultra)
    assert len(items) == 5

    required_anchors = (
        (
            "material product",
            "architecture",
            "safety",
            "milestone decision",
            "genuinely unresolved",
            "multiple subsystems",
        ),
        ("wrong decision", "high-consequence", "long-lived lock-in"),
        (
            "primarily requires synthesis",
            "adversarial reasoning",
            "decision design",
            "beyond a bounded gpt-5.6 sol / high implementation",
        ),
        ("one primary issue", "one coherent artifact", "proposal", "pr"),
        (
            "written stop",
            "durable-checkpoint",
            "minion-ownership",
            "handoff plan",
            "before work starts",
        ),
    )
    for item, anchors in zip(items, required_anchors, strict=True):
        assert_required_anchors(item, anchors)

    assert_required_anchors(
        ultra,
        (
            "only when all five",
            "if any condition is false",
            "explicit external-orchestrator authorization",
            "written rationale",
        ),
    )


def test_severity_rows_and_worker_risk_do_not_structurally_set_ultra_routes() -> None:
    routing = read(ROUTING_PATH)
    ultra = section(routing, "4. Ultra admission contract")
    independent_routes = section(
        routing,
        "2. Two independent, smallest-sufficient routing decisions",
    )

    assert_required_anchors(
        ultra,
        ("critical", "milestone", "p0", "p1", "maximum worker risk", "never admits ultra alone"),
    )
    assert_required_anchors(
        independent_routes,
        (
            "highest-risk worker does not automatically set the coordinator route",
            "does not automatically pass its route to every worker",
            "smaller route",
            "larger route is not admitted",
        ),
    )
    prohibited_rows: list[tuple[Path, tuple[str, ...]]] = []
    for path in POLICY_PATHS:
        for header, rows in markdown_tables(read(path)):
            if "coordinator" not in header or "reasoning" not in header:
                continue
            work_class_index = next(
                index for index, cell in enumerate(header) if "class" in cell
            )
            coordinator_index = header.index("coordinator")
            reasoning_index = header.index("reasoning")
            for row in rows:
                route = normalize(" | ".join((row[coordinator_index], row[reasoning_index])))
                if (
                    "ultra" in route
                    and any(
                        label in normalize(row[work_class_index])
                        for label in ("critical", "milestone", "p0", "p1")
                    )
                ):
                    prohibited_rows.append((path, row))
    assert not prohibited_rows, f"Severity/label table rows admit Ultra: {prohibited_rows}"


def test_one_writer_read_only_minions_and_non_overlapping_ownership_are_required() -> None:
    governance = section(read(ROUTING_PATH), "5. Coordinator and minion governance")
    assert_required_anchors(
        governance,
        (
            "one write coordinator by default",
            "second writer",
            "explicitly authorizes",
            "completely disjoint",
            "durable content-addressed checkpoint",
            "minions are read-only by default",
            "finite maximum",
            "stable child identities",
            "no-mutation rule",
            "smallest sufficient route",
            "never inherit ultra",
        ),
    )


def test_checkpoints_tmp_protection_and_restartable_receipts_are_required() -> None:
    delivery = section(
        read(ROUTING_PATH),
        "8. Durable checkpoints, restartable validation, and receipts",
    )
    assert_required_anchors(
        delivery,
        (
            "before a long full-suite",
            "coverage",
            "compatibility",
            "fuzz/mutation",
            "multi-review",
            "remote, content-addressed checkpoint",
            "commit and tree shas",
            "no sole valuable copy",
            "/tmp",
            "ephemeral worker workspace",
            "not parked",
            "not ready",
            "not complete",
            "restartable",
            "machine-readable receipt",
            "remaining work",
        ),
    )


def test_runtime_honesty_and_ci_truthfulness_are_required() -> None:
    routing = read(ROUTING_PATH)
    runtime = section(routing, "6. Actual-runtime honesty and route deviations")
    assert_required_anchors(
        runtime,
        (
            "requested and actual coordinator model/reasoning",
            "requested and actual worker model/reasoning",
            "not visible",
            "no silent downgrade",
            "fallback",
            "inheritance",
            "substitution",
            "stop/escalation condition",
        ),
    )
    assert_required_anchors(
        section(routing, "9. Validation, exact-head review, and CI truthfulness"),
        (
            "automatic actions",
            "manually dispatched actions",
            "skipped jobs",
            "unavailable ci",
            "infrastructure-blocked ci",
            "only an observed applicable success is green",
        ),
    )
    for path in POLICY_PATHS:
        assert "not visible" in normalize(read(path)), f"{path} omits runtime-identity honesty"


def test_task_and_pr_templates_capture_identity_ownership_checkpoints_and_ready_review() -> None:
    task = read(TASK_PACKET_PATH)
    assert_field_lines(
        section(task, "Agent identity"),
        (
            "AGENT_ID",
            "PARENT_AGENT_ID",
            "ISSUE",
            "LANE",
            "PHASE",
            "AUTHORIZED_BASE",
            "AUTHORIZED_TREE",
            "BRANCH",
            "REQUESTED_MODEL",
            "REQUESTED_REASONING",
        ),
    )
    assert_required_anchors(
        section(task, "Whole-PR routing"),
        ("routing rationale", "smaller sufficient route", "fallback", "substitution"),
    )
    assert_required_anchors(
        section(task, "Delegated slice routing"),
        (
            "agent_id",
            "parent_agent_id",
            "read-only",
            "exact owned sources/paths/symbols",
            "non-overlapping ownership",
        ),
    )
    assert_required_anchors(
        section(task, "Durable checkpoint and handoff plan"),
        ("durable ref", "content-hash evidence", "sole valuable copy", "receipt location"),
    )
    assert_required_anchors(
        section(task, "Draft-to-Ready review inspection"),
        (
            "draft-to-ready transition",
            "ready-triggered review",
            "all newer comments inspected",
            "every review thread inspected",
        ),
    )

    pr_report = read(PR_REPORT_PATH)
    pr_routing = section(pr_report, "Routing report")
    assert_field_lines(
        pr_routing,
        (
            "Coordinator AGENT_ID",
            "Coordinator PARENT_AGENT_ID",
            "Routing rationale",
        ),
    )
    assert_required_anchors(
        pr_routing,
        (
            "exact non-overlapping ownership",
            "read-only minions",
            "one write coordinator by default",
        ),
    )
    assert_required_anchors(
        section(pr_report, "Validation"),
        (
            "durable checkpoints and bounded receipts",
            "machine-readable",
            "sole valuable copy",
        ),
    )
    assert_required_anchors(
        section(pr_report, "Review and readiness ledger"),
        (
            "draft-to-ready transition",
            "ready-triggered review",
            "all comments newer than ready inspected",
            "every review thread inspected after ready",
        ),
    )


def test_noncanonical_policy_sources_reference_the_routing_authority() -> None:
    for path in POLICY_PATHS:
        if path == ROUTING_PATH:
            continue
        assert "codex-model-routing.md" in read(path), (
            f"{path.relative_to(REPO_ROOT)} does not reference the routing authority"
        )


def test_workspace_propagates_bounded_delivery_and_post_ready_inspection() -> None:
    workspace = read(WORKSPACE_PATH)
    assert_required_anchors(
        workspace,
        (
            "smallest route",
            "one write coordinator by default",
            "read-only",
            "non-overlapping",
            "no sole valuable copy in /tmp",
            "restartable validation slices",
            "machine-readable receipts",
            "draft becomes ready",
            "every triggered review",
            "all newer comments",
            "every thread",
        ),
    )
