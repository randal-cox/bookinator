# Bookinator implementation priorities

## Reuse before invention

Before building or styling any UI behavior, search the existing codebase for the closest shipped component and its interaction contract. Reuse or extend that component first.

For dialogs specifically, use Bookinator's `.backdrop` + `.standard-dialog` structure and the shared dialog functions in `web/app.js`. Every dialog must inherit the standard close button, backdrop behavior, Escape handling, focus behavior, and `installMovableDialog()` support. Do not create a one-off modal overlay.

Controls inside dialogs must also reuse the application's existing button and control patterns. Do not introduce a one-off button, menu, toggle, or visual treatment merely because the surrounding dialog is new.

When a new reusable variation is genuinely needed, add it to the shared primitive before consuming it in a feature. Treat duplicated interaction code as a bug.
