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


def numbered_items(markdown: str) -> list[str]:
    items: list[list[str]] = []
    for line in markdown.splitlines():
        match = re.match(r"^(?P<number>\d+)\.\s+(?P<text>.+)", line)
        if match:
            items.append([match.group("text")])
        elif items and (line.startswith("   ") or line.startswith("      ")):
            items[-1].append(line.strip())
    return [normalize(" ".join(item)) for item in items]


def assert_contains_concepts(text: str, concepts: tuple[str, ...]) -> None:
    normalized = normalize(text)
    missing = [concept for concept in concepts if normalize(concept) not in normalized]
    assert not missing, f"Missing policy concepts: {missing}"


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

    canonical_header = "| Work class | Coordinator | Reasoning | Bounded-contract test |"
    assert sum(read(path).count(canonical_header) for path in POLICY_PATHS) == 1


def test_ultra_requires_all_five_unweakened_admission_conditions() -> None:
    ultra = section(read(ROUTING_PATH), "4. Ultra admission contract")
    items = numbered_items(ultra)
    assert len(items) == 5

    required_concepts = (
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
    for item, concepts in zip(items, required_concepts, strict=True):
        assert_contains_concepts(item, concepts)

    assert_contains_concepts(
        ultra,
        (
            "only when all five",
            "if any condition is false",
            "explicit external-orchestrator authorization",
            "written rationale",
        ),
    )


def test_labels_and_worker_risk_never_admit_or_force_ultra() -> None:
    routing = read(ROUTING_PATH)
    routing_normalized = normalize(routing)
    ultra = section(routing, "4. Ultra admission contract")
    independent_routes = section(
        routing,
        "2. Two independent, smallest-sufficient routing decisions",
    )

    assert_contains_concepts(
        ultra,
        ("critical", "milestone", "p0", "p1", "maximum worker risk", "never admits ultra alone"),
    )
    assert_contains_concepts(
        independent_routes,
        (
            "highest-risk worker does not automatically set the coordinator route",
            "does not automatically pass its route to every worker",
            "smaller route",
            "larger route is not admitted",
        ),
    )
    forbidden_table_row = re.compile(
        r"\|\s*(?:critical(?:\s*/\s*milestone)?|milestone|p0|p1)\s*\|"
        r"\s*gpt-5\.6\s+sol\s*\|\s*ultra\s*\|",
        re.IGNORECASE,
    )
    assert not forbidden_table_row.search(routing)
    assert "formal milestone uses ultra" not in routing_normalized


def test_one_writer_read_only_minions_and_non_overlapping_ownership_are_required() -> None:
    governance = section(read(ROUTING_PATH), "5. Coordinator and minion governance")
    assert_contains_concepts(
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
    assert_contains_concepts(
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


def test_runtime_honesty_and_no_silent_route_substitution_are_required() -> None:
    routing = read(ROUTING_PATH)
    runtime = section(routing, "6. Actual-runtime honesty and route deviations")
    assert_contains_concepts(
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
    for path in POLICY_PATHS:
        assert "not visible" in normalize(read(path)), f"{path} omits runtime-identity honesty"


def test_task_and_pr_templates_capture_identity_ownership_checkpoints_and_ready_review() -> None:
    template_requirements = {
        TASK_PACKET_PATH: (
            "agent identity",
            "agent_id",
            "parent_agent_id",
            "routing rationale",
            "exact owned sources/paths/symbols",
            "read-only",
            "non-overlapping ownership",
            "durable checkpoint",
            "machine-readable receipt",
            "draft-to-ready",
            "ready-triggered review",
            "all newer comments inspected",
            "every review thread inspected",
        ),
        PR_REPORT_PATH: (
            "coordinator agent_id",
            "coordinator parent_agent_id",
            "routing rationale",
            "exact non-overlapping ownership",
            "read-only minions",
            "durable checkpoints and bounded receipts",
            "machine-readable",
            "draft-to-ready transition",
            "ready-triggered review",
            "all comments newer than ready inspected",
            "every review thread inspected after ready",
        ),
    }
    for path, requirements in template_requirements.items():
        assert_contains_concepts(read(path), requirements)


def test_workspace_propagates_bounded_delivery_and_post_ready_inspection() -> None:
    workspace = read(WORKSPACE_PATH)
    assert_contains_concepts(
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
