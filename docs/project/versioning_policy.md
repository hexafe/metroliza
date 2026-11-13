# Metroliza Versioning Policy

Status: Active decision and release-version contract

Owner: Product Owner / release maintainer

Last reviewed: 2026-11-13 (versioning adoption only)
Decision: [#1228](https://github.com/hexafe/metroliza/issues/1228), under
[#920](https://github.com/hexafe/metroliza/issues/920)

## Adopted product versions

The Product Owner adopted **`0.8.0-dev.1`** as the next public version on 2026-11-13.
This replaces the calendar RC1/six-digit public-label convention for new deliveries.
The accepted current product scope targets `0.8.0`; the distinct `1.0.0` product milestone
requires both outcomes below. Assigning a version does not prove implementation, CI,
artifact qualification, user acceptance or release approval.

| Version | Meaning | Example |
|---|---|---|
| `MAJOR.MINOR.PATCH-dev.N` | A development package for the named target scope | `0.8.0-dev.1`, then `0.8.0-dev.2` |
| `MAJOR.MINOR.PATCH-rc.N` | A frozen release candidate for that target scope | `0.8.0-rc.1`, then `0.8.0-rc.2` |
| `MAJOR.MINOR.PATCH` | The release owner's accepted declared scope | `0.8.0` |

`N` is a positive, monotonically increasing integer within the target version and channel.
It is a package/candidate sequence, never a date. New changed distributed bytes receive a new
version identity; do not overwrite an earlier package or reuse its receipts. A rebuild is a new
package too. Development and RC counters belong to their respective channels. The transition
from a qualified RC to a stable identity still needs the applicable promotion decision and exact
source/artifact evidence; changing or removing a suffix is not qualification.

After an accepted `0.8.0`, compatible bug fixes target a patch such as `0.8.1`, and a new accepted
feature scope targets a minor such as `0.9.0`, each with its own `-dev.N` / `-rc.N` preparation.
Compatibility-breaking changes require an explicit scope/migration decision. A major number
cannot bypass the `1.0.0` completion contract or existing compatibility requirements.

## Version, date and immutable evidence

Canonical public identity comes from [`src/metroliza/app/version.py`](../../src/metroliza/app/version.py).
Release notes, About, package names and recorded runtime/report provenance must agree on the
public version. Technical encodings required by a package platform remain an implementation
mapping, not a second human-facing version scheme.

The supported profile is stable, `-dev.N` or `-rc.N` only (no alpha/beta or `+metadata`), with
core components `0..65535` and counters `1..19999`. PE `FileVersion`/`ProductVersion` strings keep
the exact canonical public version; their numeric four-tuple projects the last component as
`dev.N = N`, `rc.N = 20000 + N`, stable `= 65535`. `VERSION_DATE` is an empty deprecated import
compatibility alias, never a current identity/date. Historical calendar labels are accepted only
by historical readers; they are not valid new-delivery labels.

The date is separate: record the actual package build date as **`YYYY-MM-DD`**, derived from its
real `built_at_utc` provenance. Keep the full UTC timestamp in the artifact evidence. Do not derive
a date from `dev.N`, `rc.N`, a version component or an artificial year. A source version assignment
before a build does not establish when that artifact was built. Legacy compatibility fields must
not be presented as the current actual build date.

Tags use the exact public version prefixed with `v`, for example `v0.8.0-dev.1`,
`v0.8.0-rc.1` and `v0.8.0`, when their separately authorized publication is performed.
Published tags/packages are immutable. Record exact source commit/tree, build timestamp,
EXE/ZIP identity and hashes, dependency/notices inventory, actual CI/review/package results and
release-owner disposition. A date alone is not a unique artifact identity.

Historical names such as `2026.09rc1(261119)`, original tags, archives, source SHAs and failed
receipts retain their actual bytes and meanings. Do not rename old files or reinterpret old
six-digit identifiers as new semantic versions. This decision changes no persisted data schema
or archived acceptance state.

## Branches and release gates

The [branching strategy](../release_checks/branching_strategy.md) still owns `dev` for daily
integration, `rc` for approved frozen-candidate work and `main` for separately approved
production/history. Version channels do not create extra permanent branches or automatically
promote any ref. Use the existing exact-head review/CI/merge gates and the
[release checklist](../release_checks/release_candidate_checklist.md); development-package,
RC qualification, private/manual acceptance and stable release remain distinct.

The [release status hub](../release_checks/release_status.md) and each version's Issue/PR ledger
carry actual delivery evidence. New metadata or a policy merge does not declare a new EXE built,
tested, delivered or accepted. Existing outstanding manual/private/live-service/legal criteria
retain their disposition; a version bump neither closes them nor introduces a new approval flow.

## Additional `1.0.0` product milestone

Both targets below are mandatory for `1.0.0`, in addition to the applicable declared-scope release
and quality gates. They do not require completion of all eight roadmap phases or every clause of
each linked epic. The linked Issues retain ownership of their relevant existing contracts; record
concrete accepted evidence for this milestone instead of duplicating epics or silently expanding
the dependency graph.

### Complete external-LLM parser authoring package

A user can give a self-contained package to an **external LLM** and use the resulting supported
parser/profile in Metroliza's normal offline workflow. The package must include:

- complete instructions, allowed output boundaries and the steps for using/repairing the package;
- parser APIs/contracts, data schemas, supported input/output formats and normalization rules;
- usable examples and sample/expected-results fixtures covering the declared supported format;
- deterministic package/schema/parser validation with complete expected-value/row checks;
- actual supported plugin/profile discovery and import, followed by verified database persistence
  and readback through Metroliza's owned import/DB path.

Metroliza retains ownership of database writes; generated parsers return the documented result
contract. Existing sample/privacy, trust, approval and no-network/no-arbitrary-execution boundaries
remain. The [parser specification](../parser_plugins/parser_plugin_specification.md) owns the
precise YAML-profile and advanced Python-plugin routes and their existing validation contracts.

Relevant issue ownership: [#950](https://github.com/hexafe/metroliza/issues/950) for external LLM
handoff/generation/repair clauses, [#951](https://github.com/hexafe/metroliza/issues/951) for the
relevant parser interfaces, [#928](https://github.com/hexafe/metroliza/issues/928) for parser
lifecycle, [#927](https://github.com/hexafe/metroliza/issues/927) for normal import, and
[#930](https://github.com/hexafe/metroliza/issues/930) for the relevant DB integrity/persistence
boundary. This milestone does **not** require #950's optional built-in provider/API/network
integration or completion of unrelated analysis/report SDK interfaces.

### Fully unified, complete reports

The supported reporting scope must be complete and consistently presented across its reporting
flows, with agreed values, labels, scope/method/warning/unavailable semantics and complete output
content. Demonstrate the relevant canonical-result and GUI/HTML/Excel parity and full report
journeys; a shared renderer alone or one successful partial export does not prove this target.

Relevant issue ownership: [#917](https://github.com/hexafe/metroliza/issues/917) for the shared
report/result/provenance contract, [#936](https://github.com/hexafe/metroliza/issues/936) and
[#937](https://github.com/hexafe/metroliza/issues/937) for complete workbook/offline-dashboard
outputs, and [#935](https://github.com/hexafe/metroliza/issues/935) for their applicable preset/scope
contract. Existing Reports/curation and shell contracts remain with
[#954](https://github.com/hexafe/metroliza/issues/954) and
[#945](https://github.com/hexafe/metroliza/issues/945) where the accepted report journeys consume
them. These references do not make all features of those epics new `1.0.0` prerequisites.

[#925](https://github.com/hexafe/metroliza/issues/925) remains the product backlog umbrella;
[#920](https://github.com/hexafe/metroliza/issues/920) owns version/release policy. No existing
capability is marked complete solely by adopting `0.8.0-dev.1` or stating these `1.0.0` targets.
