// Open MCT does not paint in headless Chrome; use a visible window briefly and try to open the imagery object.
import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";
const b = await chromium.launch({ channel: "chrome", headless: false, args: ["--window-position=0,0"] });
const p = await b.newPage({ viewport: { width: 1280, height: 720 } });
await p.goto("http://localhost:9000/", { waitUntil: "domcontentloaded", timeout: 60000 });
await p.waitForTimeout(15000);
for (const name of ["fprime-project", "DoomGround"]) {
  const item = p.locator(".c-tree__item", { hasText: name }).first();
  if (await item.count()) { const tri = item.locator(".c-disclosure-triangle").first(); if (await tri.count()) { await tri.click(); await p.waitForTimeout(3000); } }
  else console.log("tree item not found:", name);
}
const frame = p.locator(".c-tree__item", { hasText: "DoomFrame" }).first();
if (await frame.count()) { await frame.locator(".c-tree__item__name, .c-object-label__name").first().click(); await p.waitForTimeout(8000); console.log("opened DoomFrame", p.url()); }
await p.screenshot({ path: "out/stack/openmct.png" });
console.log("saved");
await b.close();
