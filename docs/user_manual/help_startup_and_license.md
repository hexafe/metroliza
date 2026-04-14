# Help, Startup, and License

## Startup and license checks

This is a short support/reference page for small dialogs and startup behavior.

Metroliza can perform an optional license validation step when the app starts.

If license verification is not enabled, the app opens normally.

If license verification is enabled and the license check fails, the app does not continue into the main window.

## Invalid license / hardware ID dialog

If there is no valid license, Metroliza can show a blocking dialog that includes a **Hardware ID** field.

This dialog is there so the user can copy the machine’s hardware ID and send it to the app author when requesting or resolving a license.

In practical terms:

- the app shows the license problem,
- it shows the hardware ID,
- app launch is prevented until the license issue is resolved.

## About

The **About** dialog is available from the main window menu.

It shows:

- the Metroliza version,
- license day-count information when that information is available,
- author/project attribution,
- the project GitHub link.

Use it when you need a quick version check or project reference.

## Release notes

The **Release notes** dialog is also available from the main window menu.

It shows short, non-technical release notes inside the app, plus a brief archive of earlier versions.

Use it when you want to review what changed in the current version without leaving the application.
