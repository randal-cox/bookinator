# Common Ground conformance ledger

Updated 2026-10-16. This ledger records shipped evidence and remaining
exceptions; it is not a blanket declaration that Bookinator conforms.

| Contract | Current evidence | State | Next boundary |
| --- | --- | --- | --- |
| Installable Commons | `@inator/dev-tools` and `@inator/ui` are pinned local archives; `./bin/inator doctor` verifies the installation. | Conforming | Keep exact archive and lockfile evidence. |
| Application shell | Outer header, navigation, Workspace utility, responsive menu, and compact footer use `mountInatorAppShell`. | Conforming | Preserve Bookinator routes during future shell changes. |
| Global Workspace | A shared capability registry exposes browser-local attribution Identity, complete-library Backup, and the low-frequency Machine surface. | Conforming | Add Errors only after Book has a durable incident store. |
| Consumer functional acceptance | `npm run test:functional` starts an isolated real server and Chrome, uploads a public-domain manuscript, verifies title/author inference, saves and reloads library state, exercises Pipeline and Workspace Identity, checks domain navigation, and repeats the rendered library at exactly 390px. Screenshots and a structured observation report are retained under `evidence/browser-functional/`. | Conforming for the mapped journeys | Expand the product-owned adapter as new Book contracts become consequential; Commons package tests and the UI audit do not replace this consumer journey. |
| Book workspace | Identity, Analysis, Explore, and manuscript tools remain Bookinator-owned domain navigation, distinct from global Workspace. | Intentional product seam | Do not rename, flatten, or move these tabs into global Workspace. |
| Footer information architecture | About and Docs are ordinary links. Resources requires a saved developer/team role. Governance and history records live in About. | Conforming | Keep the About record shelf complete. |
| Tooltips | Native `title` attributes and Bookinator's duplicate tooltip runtime were removed. Compact and explanatory hints now use `setInatorTooltip`. | Conforming | Exercise pointer, focus, and narrow-screen behavior in the domain browser assay. |
| Pipeline Tidy | The shared queue is rendered, but Bookinator suppresses Tidy because completed analyses are durable manuscript evidence and its server has no honest remove-completed transition. | Dated audit exception; owner: Bookinator pipeline | Define archive/hide semantics jointly with the Commons pipeline contract before exposing the control. Review by 2027-01-14. |
| Dialogs | Bookinator uses its established `.backdrop` and `.standard-dialog` lifecycle, including literal dialog markup. | Dated audit exception; owner: Bookinator UI | Adapt the lifecycle to `createDialogSurface` before migrating individual dialogs. Review by 2027-01-14. |
| Button bars | Library and pipeline bars remain product-owned implementations. | Dated audit exception; owner: Bookinator UI | Migrate real consumers to `createToolButton`/`decorateToolControl`. Review by 2027-01-14. |
| List views | Native tables were reviewed and marked `data-inator-native-table`: they present analytical matrices and portable-report facts rather than the durable book collection. | Conforming with declared semantic seam | Re-evaluate any table that begins owning collection selection, sorting, or actions. |
| Typography | Legacy styles contain below-floor text. The 2026-10-16 audit retains this as visible debt rather than calling it readable. | Dated audit exception; owner: Bookinator UI | Inventory each match in the live desktop and 390px assay, then raise or remove it. Review by 2027-01-14. |
| Application canvas | Bookinator intentionally uses a warm canvas rather than Commons white. | Advisory product distinction | Test contrast and hierarchy; keep product color bounded if it harms standard navigation legibility. |
| Python and local state | Python serving, manuscript data, analysis artifacts, reviewer state, and browser preferences are unchanged. | Preserved | Language and storage ownership stay product-specific. |

## Live pipeline acceptance

The 2026-10-16 Adversaries assay imported the public-domain *The Dunwich
Horror* fixture into an isolated data root and exercised the production
chapter-first scheduler. Four authored chapters reached durable development
checkpoints; advancing each checkpoint preserved prior artifact hashes. The
assay observed the combined Summary/Dossier/LLM Review read, cumulative
context, GLiNER, Emotions, Tags, Smells, and the human-review boundary.

Operational completion did not become a quality pass. The first two legacy
specimens had exact anchors but missed their ending movement and emitted empty
Review evidence. Chapter 3 attempt 1 was rejected for omitting its final
quarter. Attempt 2 reached the ending and populated Review evidence, then was
rejected for off-by-one cast corrections, unresolved participant IDs, and the
unsupported claim that Wilbur was Old Whateley's son. The frozen reports and
qualitative reviews under `evidence/pipeline-acceptance/` preserve that
progression. Chapter 4 then passed exact-anchor, ending, referential, kinship,
and Review-evidence checks but still failed for a short-name/full-name cast
duplicate, incidental cast, and rejected Summary claims left uncorrected in the
prose overview.

The resulting contract now requires final-quarter action obligations, stable
canonical identity under a fallible verifier, resolved projection subjects,
locally supported kinship assertions, exact Review evidence, and a quiet
retryable quality failure that cannot kill or route around the single queue
worker. This ledger remains **not a blanket editorial-quality pass**.

## LLM visual inspection

The live desktop Pipeline, desktop Workspace Identity, and exactly-390px Books
surface were inspected separately from the automated browser journey. The
shell, centered Identity form, manuscript navigation, active-stage badges,
chapter-first work ledger, bounded checkpoint state, mobile command layout,
and lack of horizontal overflow were coherent and readable.

Two polish findings remain visible: the desktop pipeline's estimate/progress
microcopy is dense at ordinary viewing distance, and the top navigation's
manuscript label truncates aggressively while the full title occupies a very
large content heading. Neither finding invalidates the exercised controls, but
both belong in the next visual-design pass rather than disappearing behind the
functional result.

## Capability truth

Global Workspace deliberately exposes only:

- **Identity** — browser-local attribution names and explicit developer/team
  roles, persisted only when Save is pressed.
- **Backup** — Bookinator's complete `.bookinator` library archive and existing
  restore endpoint. Existing books are never overwritten silently; collisions
  remain explicit failures and direct the user to the established import flow.
- **Machine** — host readiness plus Bookinator's local model inventory and
  assignments. It lives under Workspace because it is setup and maintenance,
  not part of the day-to-day manuscript workflow.

Errors and a separately generalized software inventory are not advertised in
this slice. Machine retains Bookinator's proven product UI while its evidence
contracts are prepared for broader Commons extraction.

## Audit interpretation

The dated UI baseline is an expiring inventory of known legacy debt, not proof
of conformance. New findings still fail the ratchet. A baseline finding may be
closed only by executable browser evidence or by a new explicit review that
names the product owner, the missing shared behavior, and an expiry date.

Commons tests prove shared primitives in the Commons repository; they do not
automatically prove that a consumer wired those primitives correctly. The
Bookinator browser journey therefore composes two layers: standard-app
obligations such as shell identity, Workspace persistence, and 390px reflow,
plus Book-owned obligations such as manuscript inference, priority, library
search persistence, book workspace structure, and a live pipeline projection.
Every Inator consumer needs the same pattern: inherited contract journeys with
a product adapter, followed by domain-functional journeys that execute its own
claims.
