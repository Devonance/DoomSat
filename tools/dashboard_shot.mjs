// Screenshot (or record) the mission dashboard at 1920x1080 with Playwright's bundled Chromium.
//   node tools/dashboard_shot.mjs shot out/dashboard.png
//   node tools/dashboard_shot.mjs record out/recording 600     (seconds; writes a .webm into that folder)
import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";

const [mode = "shot", target = "out/dashboard.png", seconds = "60"] = process.argv.slice(2);
const url = process.env.DASHBOARD_URL || "http://localhost:8070/";
const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  ...(mode === "record" ? { recordVideo: { dir: target, size: { width: 1920, height: 1080 } } } : {}),
});
const page = await context.newPage();
await page.goto(url, { waitUntil: "load" });
await page.waitForTimeout(mode === "record" ? Number(seconds) * 1000 : 3000);
if (mode === "shot") {
  await page.screenshot({ path: target });
  console.log("wrote", target);
}
await context.close();
await browser.close();
if (mode === "record") console.log("video written to", target);
