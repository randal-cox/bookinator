import {
  createWorkspaceCapabilityRegistry,
  createWorkspaceHost,
  createStandardProductShellPolicy,
  defineProductInformationContract,
  mountInatorAppShell,
  normalizeWorkspaceIdentity,
  productShellFooterLinks
} from "/commons/@inator/ui/index.js";

const identityKey = "bookinator.workspace-identity.v1";
let workspaceHost = null;
let pendingRestoreFile = null;

export function loadBookinatorIdentity() {
  try {
    return normalizeWorkspaceIdentity(JSON.parse(localStorage.getItem(identityKey) || "{}"));
  } catch {
    return normalizeWorkspaceIdentity();
  }
}

function saveBookinatorIdentity(identity) {
  const saved = normalizeWorkspaceIdentity(identity);
  localStorage.setItem(identityKey, JSON.stringify(saved));
  return saved;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function createBackupAdapter() {
  let controller = null;
  let model = {
    workspaceName: "Bookinator library",
    backup: {state: "idle", detail: "Includes sources, analysis, reviewer state, saved reports, and provenance."},
    restore: {state: "idle", errors: []}
  };
  const update = (changes) => {
    model = {...model, ...changes, backup: {...model.backup, ...(changes.backup || {})}, restore: {...model.restore, ...(changes.restore || {})}};
    controller?.update(model);
  };
  return {
    model,
    destinationMode: "fixed",
    accept: ".bookinator,application/vnd.bookinator.project+zip",
    wording: {
      backupDescription: "Download one complete portable copy of the local Bookinator library.",
      restoreDescription: "Inspect a complete Bookinator archive, then import it without overwriting existing books.",
      restoreSafety: "Existing books are never overwritten silently",
      fixedDestination: "Current Bookinator library"
    },
    bind(value) { controller = value; },
    async onAction({action, files}) {
      if (action === "backup") {
        update({backup: {state: "working", detail: "Creating the local archive…"}});
        try {
          const response = await fetch("/api/library/export");
          if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || "Backup failed.");
          const disposition = response.headers.get("Content-Disposition") || "";
          const fallback = `bookinator-library-${new Date().toISOString().slice(0, 10)}.bookinator`;
          const filename = decodeURIComponent(disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1] || fallback);
          downloadBlob(await response.blob(), filename);
          update({backup: {state: "complete", detail: `Downloaded ${filename}.`}});
        } catch (error) {
          update({backup: {state: "failed", detail: error.message || String(error)}});
        }
      } else if (action === "inspect-backup") {
        const file = files?.[0];
        pendingRestoreFile = file || null;
        const valid = Boolean(file && /\.bookinator$/i.test(file.name));
        update({restore: valid
          ? {state: "valid", fileName: file.name, destination: "Current Bookinator library", summary: "Ready to import. Title collisions remain explicit and no existing book will be overwritten.", errors: []}
          : {state: "invalid", fileName: file?.name || "", destination: "", summary: "", errors: ["Choose a complete .bookinator archive."]}});
      } else if (action === "restore" && pendingRestoreFile) {
        update({restore: {state: "working", fileName: pendingRestoreFile.name, destination: "Current Bookinator library", summary: "Importing…", errors: []}});
        try {
          const response = await fetch("/api/library/import-bundle", {method: "POST", headers: {"Content-Type": "application/vnd.bookinator.project+zip"}, body: pendingRestoreFile});
          const result = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(result.error || "Restore failed. Use Add Book to resolve title collisions interactively.");
          update({restore: {state: "complete", fileName: pendingRestoreFile.name, destination: "Current Bookinator library", summary: `Imported ${result.imported || 0} ${result.imported === 1 ? "book" : "books"}.`, errors: []}});
          globalThis.dispatchEvent(new Event("bookinator:library-restored"));
        } catch (error) {
          update({restore: {state: "failed", fileName: pendingRestoreFile.name, destination: "Current Bookinator library", summary: "Restore stopped without overwriting existing books.", errors: [error.message || String(error)]}});
        }
      }
    }
  };
}

const bookinatorInformation = defineProductInformationContract({
  productId: "book.inator",
  records: {
    about: "src/product-information.js",
    help: "src/product-docs.js",
    privacy: "src/product-practice.js",
    security: "src/product-practice.js",
    milestones: "src/product-history.js",
    releases: "src/product-history.js",
    roadmap: "src/pages.js",
    resources: "docs/presentations/catalog.json"
  }
});

export const bookinatorShellPolicy = createStandardProductShellPolicy({
  information: bookinatorInformation,
  capabilities: ["resources", "security"],
  routes: {
    about: {href: "#about/premise", route: "about"},
    help: {href: "#help/start", route: "help"},
    privacy: {href: "#privacy", route: "privacy"},
    security: {href: "#security", route: "security"},
    milestones: {href: "#releases/milestones", route: "releases"},
    releases: {href: "#releases/history", route: "releases"},
    roadmap: {href: "#roadmap/priorities", route: "roadmap"},
    resources: {href: "#resources/library", route: "resources"}
  },
});

export function createBookinatorWorkspaceRegistry(identity = loadBookinatorIdentity()) {
  return createWorkspaceCapabilityRegistry({
    context: {roles: identity.roles},
    base: {
      identity: {href: "#/workspace/identity", route: "workspace-identity", detail: identity.shortName || "Local attribution"},
      workspace: {href: "#/workspace/backup", route: "workspace", detail: "Complete library backup"}
    },
    extensions: [{
      id: "machine",
      label: "Machine",
      detail: "Readiness and local models",
      icon: "machine",
      href: "#/machine",
      route: "machine",
      order: 240,
      createView: () => null
    }]
  });
}

export function mountBookinatorShell({active = "books", selectedBook = null} = {}) {
  const identity = loadBookinatorIdentity();
  const registry = createBookinatorWorkspaceRegistry(identity);
  let selectedAnalysisTab = "summaries";
  try {
    const remembered = JSON.parse(localStorage.getItem("bookinator.analysis-tabs.v1") || "{}");
    if (remembered[selectedBook?.id]) selectedAnalysisTab = remembered[selectedBook.id];
  } catch {}
  return mountInatorAppShell({
    workspaceRegistry: registry,
    workspaceUtility: {label: "Workspace", detail: ""},
    active,
    headerMount: document.querySelector("[data-inator-product-header]"),
    footerMount: document.querySelector("[data-inator-product-footer]"),
    brand: {href: "#/", label: "Bookinator", image: {src: "/assets/bookinator.svg", width: 47, height: 47, alt: ""}},
    navigationLabel: "Bookinator",
    navigation: [
      {href: "#/books", route: "books", label: "Books", detail: "Library"},
      {href: selectedBook ? `#/book/${selectedBook.id}/${selectedAnalysisTab}` : "#/books", route: "analysis", label: "Analysis", selectedObject: {displayName: selectedBook?.title || "", emptyLabel: "No book selected"}},
      {href: "#/pipeline", route: "pipeline", label: "Pipeline", detail: "Local queue"}
    ],
    footer: {links: productShellFooterLinks(bookinatorShellPolicy, {identity, capabilities: ["resources", "security"]})}
  });
}

export function mountBookinatorWorkspace(kind) {
  const mount = document.querySelector("#workspace-host");
  const identity = loadBookinatorIdentity();
  const registry = createBookinatorWorkspaceRegistry(identity);
  const backup = createBackupAdapter();
  workspaceHost?.destroy?.();
  workspaceHost = createWorkspaceHost({
    mount,
    registry,
    adapters: {
      identity: {
        model: identity,
        roleOptions: [
          {id: "developer", label: "Developer", description: "Show engineering and product-development resources.", icon: "inspect"},
          {id: "team", label: "Team representative", description: "Show presentation and team resources.", icon: "identity"}
        ],
        onSave: async (value) => { const saved = saveBookinatorIdentity(value); mountBookinatorShell({active: "workspace-identity"}); return saved; }
      },
      workspace: backup
    }
  });
  const controller = workspaceHost.navigate(kind === "identity" ? "identity" : "workspace");
  if (kind !== "identity") backup.bind(controller);
  return controller;
}
