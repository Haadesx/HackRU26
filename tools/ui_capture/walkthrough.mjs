#!/usr/bin/env node
/**
 * Final demo walkthrough capture (record + step screenshots) via Brave/playwright-core.
 *
 * Usage:
 *   node tools/ui_capture/walkthrough.mjs <base_url> <out_dir> <dueScanId> <wrongScanId> <mismatchScanId> <uncertainScanId> <capsuleScanId>
 *
 * It opens the dashboard, walks the judge-facing flow (Home -> Scan -> verification states ->
 * explicit "Log this dose now" -> Home), records a webm of the whole run, and writes one PNG per step.
 * The script never creates scans or fixtures itself: pass scan ids that already exist.
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const BRAVE = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const [BASE, OUT, DUE, WRONG, MISMATCH, UNCERTAIN, CAPSULE] = process.argv.slice(2);
if (!BASE || !OUT || !DUE) {
  console.error("usage: walkthrough.mjs <base_url> <out_dir> <dueScanId> [wrongScanId mismatchScanId uncertainScanId capsuleScanId]");
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  executablePath: BRAVE,
  headless: true,
  args: ["--disable-crash-reporter", "--no-first-run", "--no-default-browser-check", "--disable-gpu"],
});
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
  recordVideo: { dir: OUT, size: { width: 1440, height: 900 } },
});
const page = await ctx.newPage();
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 200)));

const steps = [];
async function step(name, route, waitMs = 1200, action = null) {
  await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(waitMs);
  let detail = "";
  if (action) {
    detail = (await action().catch((e) => `action failed: ${String(e).slice(0, 120)}`)) || "";
    await page.waitForTimeout(900);
  }
  await page.screenshot({ path: `${OUT}/${String(steps.length + 1).padStart(2, "0")}-${name}.png` });
  steps.push({ step: steps.length + 1, name, route, detail });
  console.log(`${steps.length}. ${name} ${route}${detail ? " — " + detail : ""}`);
}

await step("home", "/", 1500);
await step("scan-page", "/scan", 1000);
await step("verify-due-now", `/scan/${DUE}/verify`, 1500, async () => {
  const btn = page.getByRole("button", { name: /log this dose now/i });
  await btn.click({ timeout: 5000 });
  await page.getByText(/logged at/i).first().waitFor({ timeout: 8000 });
  return "clicked 'Log this dose now' -> 'Logged at …' shown (scan itself records nothing)";
});
await step("home-after-log", "/", 1500);
if (WRONG) await step("verify-wrong-medication", `/scan/${WRONG}/verify`, 1200);
if (MISMATCH) await step("verify-strength-mismatch", `/scan/${MISMATCH}/verify`, 1200);
if (UNCERTAIN) await step("verify-uncertain", `/scan/${UNCERTAIN}/verify`, 1200);
if (CAPSULE) await step("verify-capsule-copy", `/scan/${CAPSULE}/verify`, 1200);

const video = page.video();
await ctx.close();
const videoPath = video ? await video.path() : null;
await browser.close();
console.log(JSON.stringify({ steps, consoleErrors, video: videoPath }));
