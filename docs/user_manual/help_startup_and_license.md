# Help, Startup, and License

## Startup and license checks

This is a short support/reference page for small dialogs and startup behavior.

Metroliza can perform an optional license validation step when the app starts.

If license verification is not enabled, the app opens normally.

If license verification is enabled and the license check fails, the app does not continue into the main window.

During a normal desktop launch, Metroliza can show a small startup splash so the
user gets immediate feedback while the main window and tools load. The splash
stays visible until startup warmup is complete, so the main window is ready for
input when it becomes available. Automated startup smoke checks disable that
splash by default.

## Invalid license / hardware ID dialog

If there is no valid license, Metroliza can show a blocking dialog that includes a **Hardware ID** field.

This dialog is there so the user can copy the machine’s hardware ID and send it to the app author when requesting or resolving a license.

In practical terms:

- the app shows the license problem,
- it shows the hardware ID,
- app launch is prevented until the license issue is resolved.

### What to do if license validation fails

1. Copy the **Hardware ID** exactly as shown.
2. Send the hardware ID, your Metroliza version if you know it, and the license error text to support or the app author.
3. After you receive a corrected license, install or replace the license file using the support instructions you were given.
4. Restart Metroliza.

If the computer hardware changed, the license may no longer match the machine. Request a new license for the current **Hardware ID**.

If the license expired, request a renewed license. If the license should still be valid, check that the computer date is correct before contacting support.

## About

The **About** dialog is available from **Help > About** in the main window.

It shows:

- the Metroliza version,
- license day-count information when that information is available,
- author/project attribution,
- support/build information, and
- the project GitHub link.

Use it when you need a quick version check or project reference.

The **Support/build info** block is selectable. Copy it when reporting a problem. It includes the public version label, internal version, build number, manual location, and support URL.

## Release notes

The **Release notes** dialog is also available from **Help > Release notes** in the main window.

It shows short, non-technical release notes inside the app, plus a brief archive of earlier versions.

Use it when you want to review what changed in the current version without leaving the application.

## Opening manuals

Manual entries are available from **Help** menus in the main window and in several tool dialogs.

When you open a manual entry, Metroliza asks the default browser to open the GitHub-rendered manual page. This does not change your database or reports.

If the browser cannot be opened, Metroliza shows a message with the manual link. Copy that link into a browser manually, or send it to support if the machine cannot access GitHub.

If you are offline, the manual page may not load until network access is available.
