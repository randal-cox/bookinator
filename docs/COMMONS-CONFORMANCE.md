# Common Ground conformance ledger

Updated 2026-10-04. This ledger records shipped evidence and remaining
exceptions; it is not a blanket declaration that Bookinator conforms.

| Contract | Current evidence | State | Next boundary |
| --- | --- | --- | --- |
| Installable Commons | `@inator/dev-tools` and `@inator/ui` are pinned local archives; `./bin/inator doctor` verifies the installation. | Conforming | Keep exact archive and lockfile evidence. |
| Application shell | Outer header, navigation, Workspace utility, responsive menu, and compact footer use `mountInatorAppShell`. | Conforming | Preserve Bookinator routes during future shell changes. |
| Global Workspace | A shared capability registry exposes browser-local attribution Identity and complete-library Backup. | Conforming | Add Errors only after Book has a durable incident store. |
| Book workspace | Identity, Analysis, Explore, and manuscript tools remain Bookinator-owned domain navigation, distinct from global Workspace. | Intentional product seam | Do not rename, flatten, or move these tabs into global Workspace. |
| Footer information architecture | About and Docs are ordinary links. Resources requires a saved developer/team role. Governance and history records live in About. | Conforming | Keep the About record shelf complete. |
| Dialogs | Bookinator uses its established `.backdrop` and `.standard-dialog` lifecycle. | Partial | Adapt that primitive to the shared controller before migrating individual dialogs. |
| Button bars | Library and pipeline bars remain product-owned implementations. | Audit exception | Migrate real consumers to the shared action-bar contract. |
| List views | Library and portable-report tables remain native/product-owned. | Audit exception pending semantic review | Adopt `createListView` only where its durable-collection contract matches. |
| Typography | The Commons audit reports one below-floor treatment. | Blocking audit exception | Remove or explicitly review it; do not normalize unreadable metadata. |
| Python and local state | Python serving, manuscript data, analysis artifacts, reviewer state, and browser preferences are unchanged. | Preserved | Language and storage ownership stay product-specific. |

## Capability truth

Global Workspace deliberately exposes only:

- **Identity** — browser-local attribution names and explicit developer/team
  roles, persisted only when Save is pressed.
- **Backup** — Bookinator's complete `.bookinator` library archive and existing
  restore endpoint. Existing books are never overwritten silently; collisions
  remain explicit failures and direct the user to the established import flow.

Errors, software, models, and machine capabilities are not advertised in this
slice. Bookinator has machine/model UI, but it has not yet been adapted to those
new shared capability contracts.
