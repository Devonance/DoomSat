// Capture the whole ground segment at once: the mission dashboard, the Yamcs web UI (telemetry and commands) and
// Open MCT, one screenshot per second each, for N seconds. tools/stack_video.py turns the frames into a 1080p grid video.
//   node tools/stack_record.mjs out/stackrec 120
import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";
import { mkdirSync } from "node:fs";

const [dir = "out/stackrec", seconds = "120"] = process.argv.slice(2);
mkdirSync(dir, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", args: ["--use-gl=angle", "--ignore-gpu-blocklist"] });
const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
const tiles = [
  { name: "dashboard", url: "http://localhost:8070/" },
  { name: "yamcs-tlm", url: "http://localhost:8090/telemetry/parameters?c=fprime-project__realtime&filter=doom" },
  { name: "yamcs-cmd", url: "http://localhost:8090/commanding/history?c=fprime-project__realtime" },
  { name: "openmct", url: "http://localhost:9000/" },
];
const pages = [];
for (const t of tiles) {
  const p = await context.newPage();
  if (t.name === "dashboard") await p.setViewportSize({ width: 1920, height: 1080 });  // the dashboard is laid out for 1920 px
  try { await p.goto(t.url, { waitUntil: "load", timeout: 20000 }); } catch (e) { console.log("load failed", t.name, String(e).slice(0, 80)); }
  pages.push([t, p]);
}
await pages[0][1].waitForTimeout(4000);
const n = Number(seconds);
for (let i = 0; i < n; i++) {
  const t0 = Date.now();
  await Promise.all(pages.map(([t, p]) => p.screenshot({ path: `${dir}/${t.name}-${String(i).padStart(4, "0")}.png` }).catch(() => null)));
  const wait = 1000 - (Date.now() - t0);
  if (wait > 0) await pages[0][1].waitForTimeout(wait);
}
await browser.close();
console.log("captured", n, "seconds into", dir);
