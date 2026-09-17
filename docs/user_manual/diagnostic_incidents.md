# Diagnostic incidents

Metroliza can keep a small, private history of supervised startup and approved workflow states. This history uses generated identifiers, fixed status values, bounded counters, and build information. It does not contain imported report data, SQL, file paths, free-form logs, or native stack dumps.

A supervised launch runs the application through Metroliza's diagnostic supervisor. Only this launch path can create an incident report. Starting the application directly remains available, but a direct launch does not create supervised incident reports.

The incident viewer distinguishes a complete recording from one with rejected, dropped, coalesced, or evicted events. It also reports when the diagnostic channel ended incompletely. A workflow result can say **Domain validation: Not performed** because the recorder observes workflow boundaries and does not replace a domain validator. Native stack collection is unavailable in this version.

When a timing or loss counter reaches its recording limit, the viewer shows **At least**. That value is a lower bound, and the exported incident uses the same meaning.

An unresolved session marker means that Metroliza could not verify a clean end for that supervised session. Its cause is unknown. The marker alone is not proof of a crash.

Incidents remain only on the local computer unless you export one. **Export selected** creates a ZIP bundle for the selected incident with its safe summary and manifest. Cancellation creates nothing, and an existing destination is never replaced. The export does not include raw marker files or unrelated incidents.

Exported copies remain where you chose to save them and are outside automatic incident retention.

Storage is bounded to 20 reports, 32 MiB in total, and 14 days. Each report is at most 3 MiB. In-memory recording is bounded to 2 MiB, 2,000 events, and 300 seconds; the viewer states when those limits caused history loss.
