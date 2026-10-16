import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.BOOKINATOR_FUNCTIONAL_PORT || 4893);
const baseURL = `http://127.0.0.1:${port}`;
const dataDir = await mkdtemp(path.join(os.tmpdir(), "bookinator-functional-"));
const evidenceDir = path.join(root, "evidence", "browser-functional");
await mkdir(evidenceDir, { recursive: true });

const candidates = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium"
].filter(Boolean);
let executablePath = "";
for (const candidate of candidates) {
  try { await access(candidate); executablePath = candidate; break; } catch { /* try next */ }
}
assert.ok(executablePath, "Bookinator browser acceptance requires Chrome or Chromium.");

// This journey owns a unique port and disposable data root. It must not use
// --highlander: that fleet-level replacement mode can briefly restart a
// healthy isolated server while Chrome is loading its module graph.
const server = spawn(path.join(root, "bin", "codex_serve"), [], {
  cwd: root,
  env: {
    ...process.env,
    CODEX_BOOKINATOR_PORT: String(port),
    CODEX_BOOKINATOR_DATA_DIR: dataDir,
    NO_OPEN: "1"
  },
  stdio: ["ignore", "pipe", "pipe"]
});
let serverOutput = "";
server.stdout.on("data", (chunk) => { serverOutput += chunk; });
server.stderr.on("data", (chunk) => { serverOutput += chunk; });

async function ready() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const [health, document, application] = await Promise.all([
        fetch(`${baseURL}/api/health`),
        fetch(`${baseURL}/`),
        fetch(`${baseURL}/app.js?v=pipeline-checkpoint-204`),
      ]);
      const launcherOwnsServer = serverOutput.includes("[Bookinator]: ready.");
      if (launcherOwnsServer && health.ok && document.ok && application.ok) return;
    } catch { /* keep waiting */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Bookinator did not start.\n${serverOutput}`);
}

const observations = [];
const pass = (id, action, assertion) => observations.push({ id, status: "passed", evidence: { action, assertion } });
const pageErrors = [];
let browser;
try {
  await ready();
  browser = await chromium.launch({ headless: true, executablePath });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => pageErrors.push(`${request.failure()?.errorText || "request failed"}: ${request.url()}`));
  page.on("console", (message) => { if (message.type() === "error") pageErrors.push(message.text()); });

  await page.goto(`${baseURL}/#/books`);
  const welcome = page.getByRole("button", { name: "Meet Bookinator" });
  if (await welcome.isVisible().catch(() => false)) await welcome.click();
  await page.getByRole("heading", { name: "Books", exact: true }).waitFor();
  try {
    await page.waitForFunction(() => document.querySelector("[data-inator-product-header]")?.innerText.includes("Bookinator"));
  } catch (error) {
    const shell = await page.evaluate(() => ({
      header: document.querySelector("[data-inator-product-header]")?.outerHTML,
      scripts: [...document.scripts].map((script) => script.src),
    }));
    throw new Error(`Shared product header did not render: ${error.message}; browser errors=${JSON.stringify(pageErrors)}; shell=${JSON.stringify(shell)}; server=${serverOutput.slice(-2000)}`);
  }
  assert.match(await page.locator("[data-inator-product-header]").innerText(), /Bookinator/);
  pass("shell.identity", "loaded the live library", "named product brand and Books route rendered");

  await page.locator("#book-intake-file").setInputFiles(path.join(root, "demo-corpus", "fixtures", "the-dunwich-horror.md"));
  await page.locator("#add-dialog:not([hidden])").waitFor();
  await page.locator("#book-title").waitFor();
  await page.waitForFunction(() => document.querySelector("#book-title")?.value === "The Dunwich Horror");
  assert.equal(await page.locator("#book-author").inputValue(), "H. P. Lovecraft");
  await page.locator('.analysis-priority-picker label:has-text("Shelved")').click();
  assert.equal(await page.getByRole("radio", { name: "Shelved" }).isChecked(), true);
  await page.getByRole("button", { name: "Add to library" }).click();
  await page.waitForURL(/#\/?book\/[a-z0-9-]+\/pipeline/i);
  const bookHash = new URL(page.url()).hash;
  assert.match(await page.getByRole("heading", { name: "The Dunwich Horror", exact: true }).textContent(), /Dunwich Horror/);
  pass("domain.intake", "uploaded the public-domain Markdown fixture and saved it shelved", "title and author were inferred, the record persisted, and the product opened its workspace");

  await page.evaluate(() => { location.hash = "#/books"; });
  await page.waitForTimeout(500);
  if (!(await page.locator(".book-title-link").count())) {
    const diagnostic = await page.evaluate(async () => ({ hash: location.hash, body: document.body.innerText.slice(0, 1200), api: await fetch("/api/books").then((response) => response.json()) }));
    throw new Error(`Saved book did not render in the library: ${JSON.stringify(diagnostic)}`);
  }
  await page.locator(".book-title-link", { hasText: "The Dunwich Horror" }).waitFor();
  assert.equal(await page.locator('[data-book-priority] option:checked').textContent(), "Shelved");
  await page.locator("#search").fill("Lovecraft");
  assert.equal(await page.locator(".book-row").count(), 1);
  await page.reload();
  await page.waitForFunction(() => document.querySelector("[data-inator-product-header]")?.innerText.includes("Bookinator"));
  try {
    await page.locator(".book-title-link", { hasText: "The Dunwich Horror" }).waitFor();
  } catch (error) {
    const diagnostic = await page.evaluate(async () => ({ hash: location.hash, search: document.querySelector("#search")?.value, body: document.body.innerText.slice(0, 1200), api: await fetch("/api/books").then((response) => response.json()) }));
    throw new Error(`Saved book did not survive a browser reload: ${error.message}; diagnostic=${JSON.stringify(diagnostic)}; browser errors=${JSON.stringify(pageErrors)}`);
  }
  assert.equal(await page.locator("#search").inputValue(), "Lovecraft");
  pass("domain.library-state", "searched the live library, reloaded, and inspected priority", "shelved priority and search preference survived reload");

  await page.evaluate(() => { location.hash = "#/pipeline"; });
  await page.getByRole("heading", { name: "Pipeline", exact: true }).waitFor();
  await page.getByRole("heading", { name: "Work in priority order" }).waitFor();
  assert.match(await page.locator("#library-pipeline-progress").innerText(), /Pipeline|Stopped|Ready|Run/i);
  pass("pipeline.shared-surface", "opened Pipeline through product navigation", "shared progress and priority-order queue rendered from live server state");

  await page.evaluate(() => { location.hash = "#/workspace/identity"; });
  await page.getByRole("heading", { name: "Identity", exact: true }).waitFor();
  const identityGeometry = await page.locator(".inator-workspace-identity").evaluate((form) => {
    const formRect = form.getBoundingClientRect();
    const hostRect = form.parentElement.getBoundingClientRect();
    return {
      formCenter: formRect.left + formRect.width / 2,
      hostCenter: hostRect.left + hostRect.width / 2,
    };
  });
  assert.ok(Math.abs(identityGeometry.formCenter - identityGeometry.hostCenter) <= 2, `Identity form is not centered in its shared host: ${JSON.stringify(identityGeometry)}`);
  await page.getByLabel("Short name").fill("RD");
  await page.getByLabel("Long name").fill("Randal Demo");
  await page.getByRole("button", { name: "Developer" }).click();
  await page.getByRole("button", { name: "Team representative" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByText("Identity saved.").waitFor();
  await page.reload();
  await page.waitForFunction(() => document.querySelector("[data-inator-product-header]")?.innerText.includes("Bookinator"));
  assert.equal(await page.getByLabel("Short name").inputValue(), "RD");
  assert.equal(await page.getByLabel("Long name").inputValue(), "Randal Demo");
  assert.equal(await page.getByRole("button", { name: "Developer" }).getAttribute("aria-pressed"), "true");
  assert.equal(await page.getByRole("button", { name: "Team representative" }).getAttribute("aria-pressed"), "true");
  await page.screenshot({ path: path.join(evidenceDir, "identity-desktop.png"), fullPage: true });
  pass("workspace.identity", "verified the shared form geometry, edited both attribution fields, enabled both roles, saved, and reloaded", "the form was centered and values plus pressed role state persisted in the rendered form");

  await page.evaluate((hash) => { location.hash = hash; }, bookHash);
  await page.getByRole("heading", { name: "The Dunwich Horror", exact: true }).waitFor();
  const tabs = page.getByRole("navigation", { name: "Book workspace" });
  for (const label of ["Identity", "Analysis", "Explore", "Reviewer"]) assert.ok(await tabs.getByText(label, { exact: true }).count(), `${label} workspace group is missing`);
  pass("domain.workspace", "reopened the saved book workspace", "Identity, Analysis, Explore, and Reviewer domain groups were present");

  await page.screenshot({ path: path.join(evidenceDir, "desktop.png"), fullPage: true });
  await context.close();

  const narrow = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobile = await narrow.newPage();
  mobile.on("pageerror", (error) => pageErrors.push(error.message));
  await mobile.goto(`${baseURL}/#/books`);
  const mobileWelcome = mobile.getByRole("button", { name: "Meet Bookinator" });
  if (await mobileWelcome.isVisible().catch(() => false)) await mobileWelcome.click();
  await mobile.getByRole("heading", { name: "Books", exact: true }).waitFor();
  const overflow = await mobile.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
  assert.ok(overflow.document <= overflow.viewport + 1 && overflow.body <= overflow.viewport + 1, `390px page overflows: ${JSON.stringify(overflow)}`);
  for (const selector of ["#add-book", "[data-book-priority]", ".row-action-icon-button"]) {
    const box = await mobile.locator(selector).first().boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= 390, `${selector} is clipped at 390px: ${JSON.stringify(box)}`);
  }
  await mobile.screenshot({ path: path.join(evidenceDir, "mobile-390.png"), fullPage: true });
  pass("responsive.390", "loaded the real app at exactly 390px", "the rendered document had no horizontal page overflow");
  await narrow.close();

  assert.deepEqual(pageErrors, [], `Browser errors: ${pageErrors.join(" | ")}`);
  pass("runtime.errors", "observed both browser sessions", "no uncaught page error or console error occurred");
  await writeFile(path.join(evidenceDir, "report.json"), JSON.stringify({
    schema: "bookinator.browser-functional.v1",
    observedAt: new Date().toISOString(),
    boundary: { browser: executablePath, desktop: { width: 1280, height: 900 }, mobile: { width: 390, height: 844 }, data: "temporary isolated public-domain fixture" },
    observations
  }, null, 2) + "\n");
  console.log(`Bookinator browser-functional acceptance passed: ${observations.length}/${observations.length}`);
} finally {
  await browser?.close().catch(() => {});
  server.kill("SIGTERM");
  if (!process.env.BOOKINATOR_FUNCTIONAL_KEEP_DATA) await rm(dataDir, { recursive: true, force: true });
}
