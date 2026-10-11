#!/usr/bin/env node
/**
 * Headless capture + UI verification via Brave (playwright-core; no bundled browsers).
 *
 * Usage:
 *   node tools/ui_capture/capture.mjs <base_url> <out_prefix> [route ...]
 *   node tools/ui_capture/capture.mjs http://127.0.0.1:5299 after "/" "/scan"
 *
 * For each route it captures desktop/laptop/mobile PNGs into docs/screenshots/ui/ and
 * prints a JSON line per page with: console errors, horizontal-scroll flag, title,
 * and a text digest (so behavior/content can be compared before vs after).
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";

const BRAVE = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const BASE = process.argv[2];
const PREFIX = process.argv[3];
const ROUTES = process.argv.slice(4);
if (!BASE || !PREFIX) {
  console.error("usage: capture.mjs <base_url> <out_prefix> [route ...]");
  process.exit(2);
}
const SIZES = [
  ["mobile", 390, 844],
  ["tablet", 768, 1024],
  ["laptop", 1440, 900],
  ["desktop", 1920, 1080],
  ["wide", 2560, 1440],
];
const OUT = "docs/screenshots/ui";
mkdirSync(OUT, { recursive: true });

const slugOf = (route) => (route === "/" ? "home" : route.replace(/^\//, "").replace(/\//g, "-"));

const browser = await chromium.launch({
  executablePath: BRAVE,
  headless: true,
  args: ["--disable-crash-reporter", "--no-first-run", "--no-default-browser-check", "--disable-gpu"],
});

const summary = [];
for (const route of ROUTES.length ? ROUTES : ["/"]) {
  for (const [sizeName, width, height] of SIZES) {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    const consoleErrors = [];
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 200)); });
    page.on("pageerror", (err) => consoleErrors.push(String(err).slice(0, 200)));
    try {
      await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 30000 });
    } catch {
      await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
    }
    await page.waitForTimeout(1500); // let /state poll paint
    const info = await page.evaluate(() => ({
      title: document.title,
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      text: document.body.innerText.replace(/\s+/g, " ").slice(0, 300),
      hasSkipLink: !!document.querySelector('a[href^="#"]'),
      h1: document.querySelector("h1")?.innerText?.slice(0, 80) ?? null,
    }));
    const file = `${OUT}/${PREFIX}-${slugOf(route)}-${sizeName}.png`;
    await page.screenshot({ path: file, fullPage: true });
    summary.push({
      file,
      route,
      size: `${width}x${height}`,
      title: info.title,
      horizontalScroll: info.scrollWidth > info.innerWidth + 1,
      consoleErrors,
      hasSkipLink: info.hasSkipLink,
      h1: info.h1,
    });
    await page.close();
  }
}
await browser.close();
console.log(JSON.stringify(summary, null, 1));
