# Hexafe Groupstats Integration Handoff (Archived)

This note replaces an obsolete local Codex handoff that instructed a future agent to integrate `hexafe-groupstats`.

The integration is now implemented:

- Runtime dependency: `hexafe-groupstats[pandas]` pinned in `requirements.txt`.
- Metroliza bridge: `modules/hexafe_groupstats_adapter.py`.
- Group Analysis service entry point: `modules/group_analysis_service.py` calls the bridge instead of owning the statistical engine directly.
- Packaging coverage: PyInstaller and Nuitka packaging configs include `hexafe_groupstats`.
- Regression coverage: group-analysis service and packaging hidden-import tests cover the integration.

Retain this file only as historical context for why the standalone package became the statistical source of truth. Active Group Analysis behavior belongs in the user manual and code/tests, not in this archived handoff.
