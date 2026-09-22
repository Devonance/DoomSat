// Record the mission dashboard at 1920x1080 as a screenshot sequence (~4 fps), then tools/stack_video.py --frames
// turns it into an mp4. Playwright's recordVideo produced a 1-second file with the system Chrome, so this is the
// reliable path.
//   node tools/dashboard_record.mjs out/dashrec 120
import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";
import { mkdirSync } from "node:fs";

const [dir = "out/dashrec", seconds = "120"] = process.argv.slice(2);
mkdirSync(dir, { recursive: true });
const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
const page = await context.newPage();
await page.goto(process.env.DASHBOARD_URL || "http://localhost:8070/", { waitUntil: "load" });
await page.waitForTimeout(3000);
const end = Date.now() + Number(seconds) * 1000;
let i = 0;
while (Date.now() < end) {
  const t0 = Date.now();
  await page.screenshot({ path: `${dir}/f-${String(i++).padStart(5, "0")}.png` }).catch(() => null);
  const wait = 250 - (Date.now() - t0);
  if (wait > 0) await page.waitForTimeout(wait);
}
await browser.close();
console.log("captured", i, "frames into", dir);
