// Second pass: Open MCT needs a long settle; the F´ events extension lives at the server root.
import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";
const out = process.argv[2] || "out/stack";
const b = await chromium.launch({ channel: "chrome", args: ["--use-gl=angle", "--ignore-gpu-blocklist"] });
const ctx = await b.newContext({ viewport: { width: 1280, height: 720 } });
let p = await ctx.newPage();
p.on("console", (m) => { if (m.type() === "error") console.log("omct console:", m.text().slice(0, 160)); });
p.on("pageerror", (e) => console.log("omct pageerror:", String(e).slice(0, 160)));
await p.goto("http://localhost:9000/", { waitUntil: "load", timeout: 60000 });
await p.waitForTimeout(45000);
console.log("omct title", await p.title(), "tree items", await p.locator(".c-tree__item").count());
for (const name of ["fprime-project", "DoomGround"]) {
  const item = p.locator(".c-tree__item", { hasText: name }).first();
  if (await item.count()) { const tri = item.locator(".c-disclosure-triangle").first(); if (await tri.count()) { await tri.click(); await p.waitForTimeout(2500); } }
}
const frame = p.locator(".c-tree__item", { hasText: "DoomFrame" }).first();
if (await frame.count()) { await frame.locator(".c-tree__item__name, .c-object-label__name").first().click(); await p.waitForTimeout(6000); console.log("opened DoomFrame"); }
await p.screenshot({ path: `${out}/openmct.png` });
await p.close();
p = await ctx.newPage();
await p.goto("http://localhost:8090/ext/fprime-events", { waitUntil: "load", timeout: 60000 });
await p.waitForTimeout(6000);
console.log("fprime events title", await p.title(), p.url());
await p.screenshot({ path: `${out}/yamcs_fprime_events.png` });
await b.close();
