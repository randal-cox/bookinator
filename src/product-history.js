import { defineProductHistory } from "/commons/@inator/ui/index.js";

export const bookinatorProductHistory = defineProductHistory({
  product: "Bookinator",
  updatedAt: "2026-10-03",
  milestones: [
    {
      id: "first-working-milestone",
      title: "Holy Crap, that Worked",
      summary: "Bookinator became an end-to-end local editorial workbench that preserves a manuscript, analyzes it chapter by chapter, connects book-wide evidence, and exports a useful report.",
      status: "released",
      release: { version: "0.1.0", date: "2026-09-24", title: "Holy Crap, that Worked" },
      deliverables: [
        "Import manuscripts with source structure intact.",
        "Build durable chapter summaries, dossiers, signals, connections, and questions.",
        "Keep local pipeline state, model attempts, failures, and evidence inspectable.",
        "Export editorial reporting without sending manuscripts to a hosted service."
      ]
    },
    {
      id: "reviewer-tools",
      title: "Reviewer Tools",
      summary: "Human judgment becomes durable and attributable alongside machine proposals, source evidence, portable reports, and truthful pipeline state.",
      status: "active",
      targetVersion: "0.2.0",
      deliverables: [
        { label: "Keep reviewer annotations and sign-off distinct from model output.", state: "active" },
        { label: "Carry accepted editorial decisions into inspectable HTML and PDF reports.", state: "active" },
        { label: "Prove collision-safe backup and restore without losing source, analysis, or reviewer state.", state: "planned" },
        { label: "Close with a short smoke book and the saved Carmilla regression evidence.", state: "planned" }
      ]
    },
    {
      id: "common-ground",
      title: "Common Ground",
      summary: "Bookinator becomes an ordinary consumer of installable Inator Commons contracts while keeping manuscript, analysis, editorial, and saved-book behavior product-owned.",
      status: "next",
      targetVersion: "0.3.0",
      deliverables: [
        { label: "Replace the sibling-checkout launcher with pinned Commons packages and diagnosis.", state: "complete" },
        { label: "Adopt shared Releases and Roadmap views from one Bookinator milestone ledger.", state: "complete" },
        { label: "Move shared shell, dialogs, help, machine, lifecycle, diagnostics, and backup seams behind thin adapters.", state: "planned" },
        { label: "Preserve analysis semantics, local privacy, and saved-book compatibility throughout migration.", state: "planned" }
      ]
    },
    {
      id: "reanimator",
      title: "Reanimator",
      summary: "Structured chapter reading, source-anchored entity signals, focused semantic forks, and deterministic repair make the primary reader more disciplined and selective.",
      status: "later",
      targetVersion: "0.4.0",
      deliverables: [
        "Componentize chapter reading without allowing one failed branch to erase unrelated work.",
        "Use small local models as inspectable attention routers before expensive reading.",
        "Validate quotations, identities, relations, and correction requests deterministically.",
        "Graduate optimizations only after shadow-mode evidence protects retained editorial value."
      ]
    },
    {
      id: "engine-room",
      title: "The Engine Room",
      summary: "The analysis engine becomes a durable background service with one stable protocol for scheduling, retries, cancellation, recovery, and inspection.",
      status: "later",
      targetVersion: "0.5.0",
      deliverables: [
        "Move queue ownership out of the web-server process.",
        "Keep claims, attempts, priorities, and recovery transactionally durable.",
        "Let every controller inspect and control the same worker protocol.",
        "Behave conservatively around battery, thermal pressure, and unattended work."
      ]
    }
  ]
});
