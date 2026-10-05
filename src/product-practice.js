import { createProductPracticeViewForFooter, defineProductPrivacy, defineProductSecurity } from "/commons/@inator/ui/index.js";

export const bookinatorPrivacy = defineProductPrivacy({
  product: "Bookinator",
  updatedAt: "2026-10-04",
  summary: "Manuscripts and their derived editorial evidence remain on the editor's computer during ordinary use.",
  networkBoundary: "The browser talks to Bookinator on the loopback interface. Bookinator sends manuscript passages only to the editor's local Ollama service. Installing software or models may contact package or model registries, but those requests do not contain manuscript text.",
  data: [
    { id: "manuscripts", title: "Manuscripts and extracted text", purpose: "Create a local book project and preserve source provenance", handling: "Accepted from an explicit import, extracted locally, stored with source locations, and removable with the book", location: "The local Bookinator data directory", recipients: "Bookinator's local Python process and local extraction tools", retention: "Until the editor deletes the book or removes the data directory", controls: "Inspect the source, export the project, or delete the book from the library" },
    { id: "analysis", title: "Prompts, model output, and editorial evidence", purpose: "Analyze the manuscript and retain inspectable results", handling: "Derived locally and saved incrementally with model identity, timing, attempts, and evidence locations", location: "The book's local project", recipients: "Bookinator and the editor's local Ollama service", retention: "Until the editor deletes or replaces the book project", controls: "Inspect results and attempts, rerun affected work, export the project, or delete the book" },
    { id: "reports", title: "Reports and portable exports", purpose: "Share selected analysis without redistributing the source manuscript", handling: "Created only after an explicit export action and checked by the local privacy audit", location: "A destination chosen by the editor and Bookinator's local export history", recipients: "Only people to whom the editor gives the exported artifact", retention: "Controlled by the editor after export", controls: "Choose report sections, inspect saved exports, and remove exported files" }
  ],
  practices: [
    { id: "loopback", title: "Local application boundary", status: "implemented", detail: "The maintained launcher serves Bookinator on loopback and verifies the local health endpoint.", evidenceIds: ["server-boundary"] },
    { id: "local-models", title: "Local manuscript inference", status: "implemented", detail: "Manuscript analysis is sent to the configured Ollama service on this computer rather than to a Bookinator cloud account.", evidenceIds: ["ollama-client"] },
    { id: "bounded-exports", title: "Privacy-audited exports", status: "implemented", detail: "Portable reports reject the full manuscript, raw model responses, local paths, and network dependencies.", evidenceIds: ["export-audit"] }
  ],
  evidence: [
    { id: "server-boundary", title: "Local server tests", verifies: "Bookinator binds and reports health through its maintained local server", kind: "test", locator: "tests/test_server.py", verifiedAt: "2026-10-04" },
    { id: "ollama-client", title: "Ollama client implementation", verifies: "Model requests use the configured local Ollama endpoint", kind: "code", locator: "bookinator/ollama.py", verifiedAt: "2026-10-04" },
    { id: "export-audit", title: "Portable report privacy tests", verifies: "Model-free reports enforce the bounded export manifest", kind: "test", locator: "tests/test_server.py::test_model_free_report_is_wired_to_a_privacy_safe_manifest", verifiedAt: "2026-10-04" }
  ]
});

export const bookinatorSecurity = defineProductSecurity({
  product: "Bookinator",
  updatedAt: "2026-10-04",
  summary: "Security follows Bookinator's local workstation boundary and keeps consequential model work inspectable.",
  profiles: [
    { id: "local-workstation", title: "Local workstation", boundary: "A browser, Bookinator's loopback-only Python server, the local data directory, extraction tools, and Ollama on one editor-controlled computer", responsibility: "Bookinator maintains application boundaries; the editor controls the operating-system account, device, local models, backups, and exported files" }
  ],
  controls: [
    { id: "loopback", title: "Loopback-only service", objective: "Avoid exposing manuscripts or control endpoints as a public web service", status: "implemented", responsibility: "product", detail: "The maintained launcher and server use the local interface and expose an attributable health boundary.", evidenceIds: ["server-boundary"] },
    { id: "validated-import", title: "Validated project import", objective: "Prevent malformed archives and silent book replacement", status: "implemented", responsibility: "product", detail: "Portable project imports validate their structure and use collision-safe identities rather than overwriting existing books.", evidenceIds: ["import-tests"] },
    { id: "inspectable-work", title: "Inspectable model work", objective: "Keep failures, provenance, and model activity attributable", status: "implemented", responsibility: "product", detail: "Saved attempts retain status, model identity, timing, failure detail, source ranges, and available evidence.", evidenceIds: ["pipeline-tests"] },
    { id: "device-protection", title: "Device and account protection", objective: "Protect locally stored manuscripts and exported files", status: "not-applicable", responsibility: "customer", detail: "Bookinator does not manage operating-system login, disk encryption, physical access, or permissions on files copied outside its workspace.", evidenceIds: [] }
  ],
  evidence: [
    { id: "server-boundary", title: "Local server tests", verifies: "The application server and health boundary remain local and attributable", kind: "test", locator: "tests/test_server.py", verifiedAt: "2026-10-04" },
    { id: "import-tests", title: "Project archive tests", verifies: "Imports reject invalid bundles and preserve existing book identities", kind: "test", locator: "tests/test_server.py", verifiedAt: "2026-10-04" },
    { id: "pipeline-tests", title: "Pipeline persistence tests", verifies: "Attempts, failures, model identity, and evidence survive as inspectable local state", kind: "test", locator: "tests/test_server.py", verifiedAt: "2026-10-04" }
  ]
});

export function createBookinatorPracticePage({ root, destination } = {}) {
  return createProductPracticeViewForFooter({ mount: root, destination, privacy: bookinatorPrivacy, security: bookinatorSecurity });
}
