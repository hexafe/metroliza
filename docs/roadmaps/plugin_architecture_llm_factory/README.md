# Plugin Architecture + LLM-Assisted Plugin Factory Roadmap

## Purpose
This roadmap defines a **staged planning package** for implementing:
1. A parser plugin architecture for multi-format report ingestion (PDF, Excel, CSV, and future formats).
2. A V2 canonical parsing schema with backward compatibility.
3. An LLM-assisted plugin factory workflow to accelerate onboarding for suppliers worldwide.

This package is intentionally documentation-only and is designed to be executed **after** core plugin architecture implementation starts.

## Status
- **Current status:** Planning package prepared.
- **Execution status:** Waiting for plugin architecture implementation kickoff.
- **Owner handoff point:** Architecture team can convert each pass into Jira epics/stories.

## Scope assumptions
- Suppliers can use diverse regional conventions (decimal separators, date formats, locale-specific labels, multilingual content).
- Plugin output must conform to a canonical contract so all downstream processing is stable.
- Legacy parser behavior remains supported during migration.

## Pass index
- [Data structure decision record](./data_structure_decision_record.md)
- [Pass 1 — Foundations and interfaces](./pass_01_foundations_and_interfaces.md)
- [Pass 2 — V2 schema and compatibility adapters](./pass_02_v2_schema_and_adapters.md)
- [Pass 3 — Plugin registry, detection, and orchestration](./pass_03_registry_and_detection.md)
- [Pass 4 — LLM-assisted plugin factory](./pass_04_llm_plugin_factory.md)
- [Pass 5 — Validation, rollout, and governance](./pass_05_validation_rollout_governance.md)

## Deliverables expected from this roadmap
- A stable parser plugin interface contract.
- A canonical schema definition and migration compatibility path.
- A repeatable, test-gated LLM plugin generation workflow.
- Operational rollout controls and rollback procedures.

## Definition of done for this planning package
- All passes are approved by architecture, QA, and operations.
- Jira-ready breakdown is created from the pass checklists.
- Workstream sequencing and acceptance gates are signed off.
