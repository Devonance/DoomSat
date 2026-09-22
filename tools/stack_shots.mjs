// Screenshot the browser-facing parts of the stack (Yamcs web, Open MCT) for the tech-stack grid.
// Usage: node tools/stack_shots.mjs out/stack     (Playwright from the rover project, headless Chrome)
import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";
import fs from "node:fs";

const out = process.argv[2] || "out/stack";
fs.mkdirSync(out, { recursive: true });
const b = await chromium.launch({ channel: "chrome" });
const ctx = await b.newContext({ viewport: { width: 1280, height: 720 } });

async function shot(name, url, settle = 4000, after = null) {
  const p = await ctx.newPage();
  try {
    await p.goto(url, { waitUntil: "load", timeout: 60000 });
    await p.waitForTimeout(settle);
    if (after) await after(p);
    await p.screenshot({ path: `${out}/${name}.png` });
    console.log("shot", name, p.url());
  } catch (e) {
    console.log("failed", name, String(e).slice(0, 200));
  } finally {
    await p.close();
  }
}

const Y = "http://localhost:8090";
const C = "c=fprime-project__realtime";
await shot("yamcs_links", `${Y}/links?${C}`, 6000);
await shot("yamcs_params", `${Y}/telemetry/parameters?${C}&filter=doom`, 6000);
await shot("yamcs_health", `${Y}/telemetry/parameters/DoomSat_DoomSat/DoomSat/doom/HEALTH?${C}`, 8000);
await shot("yamcs_commands", `${Y}/commanding/history?${C}`, 6000);
await shot("yamcs_events", `${Y}/events?${C}`, 6000);
await shot("yamcs_fprime_events", `${Y}/ext/fprime-events?${C}`, 8000);
await shot("yamcs_archive", `${Y}/archive?${C}`, 8000);
await shot("openmct", "http://localhost:9000/", 20000, async (p) => {
  // expand the tree and try to open the DoomFrame imagery object
  for (const name of ["fprime-project", "DoomGround"]) {
    const item = p.locator(".c-tree__item", { hasText: name }).first();
    if (await item.count()) {
      const tri = item.locator(".c-disclosure-triangle").first();
      if (await tri.count()) { await tri.click(); await p.waitForTimeout(2000); }
    }
  }
  const frame = p.locator(".c-tree__item", { hasText: "DoomFrame" }).first();
  if (await frame.count()) { await frame.locator(".c-tree__item__name, .c-object-label__name").first().click(); await p.waitForTimeout(5000); }
});
await b.close();
