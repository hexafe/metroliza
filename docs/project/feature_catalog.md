# Metroliza Feature Catalog

Status: Active product backlog index
Owner: Product/architecture maintainer
Last reviewed: 2026-08-23
Canonical product epic: [#925](https://github.com/hexafe/metroliza/issues/925)

This catalog maps every major Metroliza product capability to a GitHub Issue. It is the bridge
between the product specification and executable development work.

## Dependency semantics

The **Strict prerequisites** column mirrors each Issue's `## Dependencies` section under the
policy in [#967](https://github.com/hexafe/metroliza/issues/967). It contains only contracts or work
that must be sufficiently accepted before the row's Issue can close, and these relationships form
an acyclic graph. Downstream consumers and cross-phase integration or conformance obligations stay
in the authoritative Issues and roadmap; they do not create reverse prerequisites.

A foundation may close with its stable contract, reference implementation, conformance fixtures
and one accepted vertical slice. Later workflow adapters must pass the shared fixtures before their
own Issues close, without blocking the foundation merely because their complete workflows land in
a later phase.

The catalog does **not** claim that every capability starts from zero. The current release-candidate
line already contains substantial implementations. A capability remains open until its supported
release contract, acceptance tests, documentation, diagnostics, compatibility behavior, and
release evidence are complete.

## Maturity legend

| Maturity | Meaning |
|---|---|
| **Release-candidate** | Substantial RC2 implementation exists, but the 1.0 contract and release acceptance gate are not fully closed. |
| **Partial** | Useful components exist, but the capability is not yet one coherent supported workflow. |
| **Experimental** | Code or research exists behind limited rollout, explicit opt-in, or unresolved product contracts. |
| **Planned** | Product outcome is approved for the roadmap, but no complete supported workflow exists. |
| **Decision required** | Existing code or product scope needs an explicit retain, extract, redesign, or remove decision. |

## 1. Workspace, import, data ownership, and curation

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Save, reopen, relink, and reproduce a complete analysis workspace | [#926](https://github.com/hexafe/metroliza/issues/926) | Planned / partial settings persistence | 2 and 5 | #915, #917, #920 |
| Unified import preflight, queue, cancellation, retry, and partial-batch recovery | [#927](https://github.com/hexafe/metroliza/issues/927) | Release-candidate | 2 | #912, #915, #916 |
| Declarative parser profiles and controlled external plugin lifecycle | [#928](https://github.com/hexafe/metroliza/issues/928) | Release-candidate | 2 and 6 | #915, #927, #944 |
| Reviewable OCR header metadata extraction, correction, and enrichment | [#929](https://github.com/hexafe/metroliza/issues/929) | Release-candidate | 2 | #927, #928, #917, #944 |
| Versioned report database and industrial-cache migration, backup, integrity, and repair | [#930](https://github.com/hexafe/metroliza/issues/930) | Release-candidate | 2 | #915, #917, #920, #944 |
| Report browser, validation review, transactional correction, and curation | [#954](https://github.com/hexafe/metroliza/issues/954) | Release-candidate | 2 | #915, #929, #930, #932 |

## 2. Selection, preparation, and reusable configuration

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Canonical typed filter expression, parser, validation, serialization, compiler, and reference-conformance foundation | [#931](https://github.com/hexafe/metroliza/issues/931) | Release-candidate, fragmented contracts | 2 | #915, #926 |
| Reusable grouping presets and characteristic-name mappings | [#932](https://github.com/hexafe/metroliza/issues/932) | Release-candidate, fragmented contracts | 2 | #915, #926, #931 |
| Versioned analysis and export presets/templates | [#935](https://github.com/hexafe/metroliza/issues/935) | Partial | 3 | #926, #931, #932, #933, #934, #917 |

## 3. Statistical analysis and engineering comparison

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Group descriptive statistics, overall comparison, pairwise comparison, effect sizes, and warnings | [#933](https://github.com/hexafe/metroliza/issues/933) | Release-candidate | 3 | #915, #917, #918, #932 |
| Capability, distribution shape, candidate-fit evidence, and risk analysis | [#934](https://github.com/hexafe/metroliza/issues/934) | Release-candidate / experimental native paths | 3 | #915, #917, #918, #933 |
| Approved cross-dataset baselines and current-versus-baseline comparison | [#948](https://github.com/hexafe/metroliza/issues/948) | Planned | 5 | #926, #932, #933, #934, #949 |

## 4. Reporting, visualization, and sharing

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Stable Excel workbook export with provenance, literal-source safety, atomic publication, and structural validation | [#936](https://github.com/hexafe/metroliza/issues/936) | Release-candidate | 3 | #917, #935, #933, #934, #903, #920 |
| Offline interactive HTML dashboard with stable manifest/DOM contracts, accessibility, and visible fallbacks | [#937](https://github.com/hexafe/metroliza/issues/937) | Release-candidate | 3 | #917, #935, #933, #934, #904 |
| Optional Google Sheets conversion with least-privilege OAuth and guaranteed local `.xlsx` fallback | [#938](https://github.com/hexafe/metroliza/issues/938) | Release-candidate / optional integration | 3 and 7 | #936, #935, #901, #920, #944 |
| Reusable visual recipes, local annotations, point marks, and compatible comparison views | [#947](https://github.com/hexafe/metroliza/issues/947) | Release-candidate / partial | 5 | #937, #935, #926, #907, #946 |
| Portable, verifiable engineering evidence bundle | [#953](https://github.com/hexafe/metroliza/issues/953) | Planned | 5 | #937, #936, #949, #926, #944, #920 |

## 5. Alternative and industrial data workflows

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Multi-file CSV/Excel Summary with typed columns, large-data mode, grouping, dashboard, and workbook output | [#939](https://github.com/hexafe/metroliza/issues/939) | Release-candidate | 4 | #931, #932, #933, #934, #937, #936, #952 |
| Cache-first Oznak/production-source configuration, bounded fetch, local analysis, and source freshness | [#940](https://github.com/hexafe/metroliza/issues/940) | Release-candidate | 4 | #930, #931, #932, #939, #944, #952 |
| Operator-ready realtime monitoring, explainable anomaly review, replay, offsets, and recovery | [#941](https://github.com/hexafe/metroliza/issues/941) | Release-candidate / controlled experimental slice | 4 | #919, #940, #930, #937, #944, #952 |

## 6. Automation, traceability, diagnostics, and support

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Supported headless CLI for preflight, import, analysis, export, replay, and validation | [#942](https://github.com/hexafe/metroliza/issues/942) | Planned / partial scripts | 5 | #912, #916, #926, #927, #935, #936, #937 |
| Watched folders and scheduled local analysis jobs with quarantine and run manifests | [#943](https://github.com/hexafe/metroliza/issues/943) | Planned | 5 | #942, #926, #927, #935, #944, #949 |
| Sanitized diagnostic bundle for support and Issue reporting | [#944](https://github.com/hexafe/metroliza/issues/944) | Partial diagnostics | 1 and 5 | #917, #920 |
| Analysis run history, provenance, artifact hashes, and reproducibility manifest | [#949](https://github.com/hexafe/metroliza/issues/949) | Partial / planned | 5 | #917, #926, #935, #942, #944 |
| Contextual onboarding, local manuals, disabled-state explanations, and troubleshooting | [#955](https://github.com/hexafe/metroliza/issues/955) | Partial | 7 | #945, #944, #902, #920 |

## 7. Application UX and accessibility

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Unified application shell, active workspace context, task ownership, recent items, and preferences | [#945](https://github.com/hexafe/metroliza/issues/945) | Release-candidate / partial consolidation | 2 and 5 | #916, #926, #944 |
| Keyboard-first, scalable, assistive-friendly desktop and generated-dashboard workflows | [#946](https://github.com/hexafe/metroliza/issues/946) | Partial | 5 and 7 | #945, #937, #904, #920 |

## 8. Extensibility, AI assistance, and performance

| Capability | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Privacy-reviewed LLM-assisted parser-profile generation and deterministic repair loop | [#950](https://github.com/hexafe/metroliza/issues/950) | Experimental foundation | 6 | #928, #944, #951, #906 |
| Stable parser, analysis, and report extension interfaces with explicit trust levels | [#951](https://github.com/hexafe/metroliza/issues/951) | Parser path advanced; analysis/report planned | 6 | #915, #917, #928, #907, #908 |
| Predictable large-dataset and long-running workflow behavior | [#952](https://github.com/hexafe/metroliza/issues/952) | Release-candidate, cross-cutting | 1–7 | #912, #914, #918, #908, #903, #904 |

## 9. Product lifecycle decisions

| Decision | Issue | Current maturity | Target phase | Strict prerequisites |
|---|---:|---|---|---|
| Retain, replace, extract, migrate, or retire legacy Group Comparison and BOM Manager entry points | [#956](https://github.com/hexafe/metroliza/issues/956) | Decision required / deprecated surfaces remain | 7 | #933, #935, #926, #920 |
| Retain, extract, redesign, or remove licensing and activation | [#957](https://github.com/hexafe/metroliza/issues/957) | Decision required / disabled by default | 7 | #920, #901, #944, #906 |

## Cross-cutting engineering contracts

The feature Issues above rely on the following engineering and governance Issues. These are not
separate product features, but they are required to deliver the feature catalog safely.

| Area | Issues |
|---|---|
| Project control and planning | #899, #902, #921, #923, #925 |
| Branch and release truth | #900, #901, #911, #920, #924 |
| Reproducible baseline and CI | #912, #913, #914, #918, #922 |
| Domain and application architecture | #915, #916, #917, #919 |
| Structural-risk reduction | #903, #904, #905 |
| Security and dependency boundaries | #906, #907, #908 |

## Feature completion rule

A feature tracking Issue may be closed only when all applicable conditions are true:

1. Its user outcome and acceptance criteria are implemented.
2. The behavior uses accepted domain/application contracts rather than an isolated UI-only path.
3. Deterministic fixtures and the appropriate unit, integration, packaging, or manual gates pass.
4. Errors, warnings, cancellation, partial success, and rollback/fallback behavior are explicit.
5. User and maintainer documentation is current.
6. Workspace, preset, manifest, and compatibility impacts are addressed.
7. Confidential data and credential boundaries are verified.
8. The supported release evidence names the exact commit/build where the feature is claimed.

Code existing on any branch is evidence of implementation progress; it is not by itself evidence
that a feature has completed this release contract.
