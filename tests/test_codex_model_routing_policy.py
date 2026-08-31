from __future__ import annotations

from collections.abc import Callable
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
CONTRADICTION_PATTERNS = {
    "automatic_ultra": (
        re.compile(
            r"\bcritical\s*/\s*milestone\s+"
            r"(?:automatically\s+)?(?:maps?|routes?|defaults?)\b.{0,80}\bultra\b"
        ),
        re.compile(
            r"\b(?:p0\s*/\s*p1|p0\s+or\s+p1|p0|p1)\s+(?:alone\s+)?"
            r"(?:admits?|requires?|forces?|routes?)\b.{0,80}\bultra\b"
        ),
        re.compile(
            r"\b(?:p0\s*/\s*p1|p0\s+or\s+p1|p0|p1)\s+"
            r"(?:work|tasks?|issues?|fix(?:es)?|changes?)\s+"
            r"(?:automatically\s+)?(?:admits?|defaults?|forces?|maps?|requires?|routes?|uses?)\b"
            r".{0,80}\bultra\b"
        ),
        re.compile(
            r"\bmaximum\s+worker\s+risk\s+automatically\s+forces?\b.{0,80}\bultra\b"
        ),
    ),
    "weakened_ultra_admission": (
        re.compile(
            r"\b(?:any|only|at\s+least)\s+(?:one|two|three|four|[1-4])\s+"
            r"(?:of\s+the\s+)?(?:conditions?\s+)?(?:is\s+|are\s+)?"
            r"(?:sufficient|required)\b"
        ),
        re.compile(r"\ball\s+five\s+conditions?\s+(?:are|is)\s+not\s+required\b"),
    ),
    "overlapping_or_mutating_workers": (
        re.compile(
            r"\b(?:additional|second|multiple|parallel)\s+writers?\b.{0,60}"
            r"\b(?:may|can|are\s+permitted|are\s+allowed)\b.{0,60}"
            r"\boverlap(?:ping)?\b.{0,60}\bwithout\b.{0,30}\bauthoriz"
        ),
        re.compile(r"\bminions?\s+(?:may|can)\s+(?:mutate|write)\b"),
        re.compile(r"\bauthorization\s+free\s+overlapping\s+writers?\b"),
    ),
    "ephemeral_or_receiptless_long_gate": (
        re.compile(
            r"\blong\s+(?:validation\s+)?gates?\b.{0,60}"
            r"\b(?:may|can|are\s+allowed)\b.{0,100}"
            r"\bsole\s+valuable\s+copy\b.{0,40}/tmp\b"
        ),
        re.compile(
            r"\b(?:may|can)\b.{0,100}\bsole\s+valuable\s+copy\b.{0,40}/tmp\b"
            r".{0,60}\b(?:without|no)\s+(?:a\s+)?(?:machine\s+readable\s+)?receipt\b"
        ),
    ),
    "silent_route_change": (
        re.compile(
            r"\b(?:may|can|is\s+allowed\s+to|are\s+allowed\s+to)\s+silently\s+"
            r"(?:downgrade|fall\s+back|substitute)\b"
        ),
        re.compile(
            r"\bsilent\s+(?:downgrade|fallback|substitution)\b.{0,40}"
            r"\b(?:allowed|permitted)\s*:?\s*(?:yes|true)\b"
        ),
        re.compile(
            r"\b(?:downgrade|fallback|substitution)\b.{0,40}\bwithout\s+"
            r"(?:escalation|approval|authorization)\b"
        ),
    ),
}
NEGATIVE_CONTROLS = {
    "automatic_ultra": (
        "CRITICAL / MILESTONE automatically maps to GPT-5.6 Sol / Ultra.",
        "P0/P1 alone admits Ultra.",
        "P0 work defaults to Ultra.",
        "P0 task maps to Ultra.",
        "P0 issue routes to Ultra.",
        "P1 fix requires Ultra.",
        "P1 change forces Ultra.",
        "P0 work admits Ultra.",
        "P1 task uses Ultra.",
        "Maximum worker risk automatically forces the coordinator to Ultra.",
    ),
    "weakened_ultra_admission": (
        "Any four conditions are sufficient.",
        "All five conditions are not required.",
    ),
    "overlapping_or_mutating_workers": (
        "Additional writers may overlap without external authorization.",
        "Minions may mutate.",
        "Authorization-free overlapping writers are permitted.",
    ),
    "ephemeral_or_receiptless_long_gate": (
        "Long gates may run with the sole valuable copy in /tmp.",
        "A coordinator may keep the sole valuable copy in /tmp with no receipt.",
    ),
    "silent_route_change": (
        "A coordinator may silently downgrade the selected route.",
        "Silent fallback allowed: yes.",
        "Model substitution without escalation is acceptable.",
    ),
}


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


def assert_contains_concepts(text: str, concepts: tuple[str, ...]) -> None:
    normalized = normalize(text)
    missing = [concept for concept in concepts if normalize(concept) not in normalized]
    assert not missing, f"Missing policy concepts: {missing}"


def assert_field_lines(text: str, fields: tuple[str, ...]) -> None:
    missing = [
        field
        for field in fields
        if re.search(rf"(?m)^\s*(?:-\s+)?{re.escape(field)}\s*:", text) is None
    ]
    assert not missing, f"Missing structural fields: {missing}"


def contradiction_hits(text: str, pattern_group: str) -> list[str]:
    normalized = normalize(text)
    return [
        pattern.pattern
        for pattern in CONTRADICTION_PATTERNS[pattern_group]
        if pattern.search(normalized)
    ]


def policy_source_texts(
    source_reader: Callable[[Path], str] = read,
) -> dict[Path, str]:
    return {path: source_reader(path) for path in POLICY_PATHS}


def assert_no_policy_contradictions(policy_texts: dict[Path, str]) -> None:
    for path in POLICY_PATHS:
        for pattern_group in CONTRADICTION_PATTERNS:
            hits = contradiction_hits(policy_texts[path], pattern_group)
            assert not hits, (
                "Contradictory routing policy in "
                f"{path.relative_to(REPO_ROOT)} for {pattern_group}: {hits}"
            )


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
                any("class" in cell for cell in header)
                and any("coordinator" in cell for cell in header)
                and any("reasoning" in cell for cell in header)
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
    assert not contradiction_hits(ultra, "weakened_ultra_admission")


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
    active_policy = "\n".join(read(path) for path in POLICY_PATHS)
    assert not contradiction_hits(active_policy, "automatic_ultra")
    prohibited_rows: list[tuple[Path, tuple[str, ...]]] = []
    for path in POLICY_PATHS:
        for _header, rows in markdown_tables(read(path)):
            for row in rows:
                normalized_row = normalize(" | ".join(row))
                if (
                    "ultra" in normalized_row
                    and any(
                        label in normalized_row
                        for label in ("critical", "milestone", "p0", "p1")
                    )
                ):
                    prohibited_rows.append((path, row))
    assert not prohibited_rows, f"Severity/label table rows admit Ultra: {prohibited_rows}"
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
    assert not contradiction_hits(governance, "overlapping_or_mutating_workers")


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
    assert not contradiction_hits(delivery, "ephemeral_or_receiptless_long_gate")


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
    assert not contradiction_hits(runtime, "silent_route_change")
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
    assert_contains_concepts(
        section(task, "Whole-PR routing"),
        ("routing rationale", "smaller sufficient route", "fallback", "substitution"),
    )
    assert_contains_concepts(
        section(task, "Delegated slice routing"),
        (
            "agent_id",
            "parent_agent_id",
            "read-only",
            "exact owned sources/paths/symbols",
            "non-overlapping ownership",
        ),
    )
    assert_contains_concepts(
        section(task, "Durable checkpoint and handoff plan"),
        ("durable ref", "content-hash evidence", "sole valuable copy", "receipt location"),
    )
    assert_contains_concepts(
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
    assert_contains_concepts(
        pr_routing,
        (
            "exact non-overlapping ownership",
            "read-only minions",
            "one write coordinator by default",
        ),
    )
    assert_contains_concepts(
        section(pr_report, "Validation"),
        (
            "durable checkpoints and bounded receipts",
            "machine-readable",
            "sole valuable copy",
        ),
    )
    assert_contains_concepts(
        section(pr_report, "Review and readiness ledger"),
        (
            "draft-to-ready transition",
            "ready-triggered review",
            "all comments newer than ready inspected",
            "every review thread inspected after ready",
        ),
    )


def test_negative_control_patterns_reject_direct_policy_contradictions() -> None:
    for pattern_group, examples in NEGATIVE_CONTROLS.items():
        for example in examples:
            assert contradiction_hits(example, pattern_group), (
                f"Negative control was not rejected by {pattern_group}: {example}"
            )


def test_automatic_ultra_patterns_allow_explicit_direct_p0_p1_negations() -> None:
    for statement in (
        "P0 work does not default to Ultra.",
        "P0/P1 never admits Ultra alone.",
    ):
        assert not contradiction_hits(statement, "automatic_ultra")


def test_every_contradiction_group_is_rejected_in_every_active_policy_source() -> None:
    sources = policy_source_texts()
    for path in POLICY_PATHS:
        for pattern_group, examples in NEGATIVE_CONTROLS.items():
            for example in examples:
                falsified_sources = {
                    source_path: f"{text}\n\n{example}" if source_path == path else text
                    for source_path, text in sources.items()
                }
                try:
                    assert_no_policy_contradictions(falsified_sources)
                except AssertionError as error:
                    message = str(error)
                    assert str(path.relative_to(REPO_ROOT)) in message
                    assert pattern_group in message
                else:
                    raise AssertionError(
                        "Injected contradiction was not rejected for "
                        f"{path.relative_to(REPO_ROOT)} / {pattern_group}: {example}"
                    )


def test_agents_read_path_rejects_silent_requested_model_substitution() -> None:
    falsifier = "A coordinator may silently substitute the requested model."

    def read_with_agents_falsifier(path: Path) -> str:
        text = read(path)
        return f"{text}\n\n{falsifier}" if path == AGENTS_PATH else text

    try:
        assert_no_policy_contradictions(policy_source_texts(read_with_agents_falsifier))
    except AssertionError as error:
        message = str(error)
        assert "AGENTS.md" in message
        assert "silent_route_change" in message
    else:
        raise AssertionError("AGENTS.md requested-model substitution falsifier was not rejected")


def test_agents_read_path_rejects_direct_p0_ultra_default() -> None:
    falsifier = "P0 work defaults to Ultra."

    def read_with_agents_falsifier(path: Path) -> str:
        text = read(path)
        return f"{text}\n\n{falsifier}" if path == AGENTS_PATH else text

    try:
        assert_no_policy_contradictions(policy_source_texts(read_with_agents_falsifier))
    except AssertionError as error:
        message = str(error)
        assert "AGENTS.md" in message
        assert "automatic_ultra" in message
    else:
        raise AssertionError("AGENTS.md direct-P0 Ultra-default falsifier was not rejected")


def test_all_active_policy_sources_reject_every_contradiction_group() -> None:
    assert_no_policy_contradictions(policy_source_texts())


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
