import { chromium } from "file:///C:/Users/Kevin/Genai/mars-rover-game/node_modules/playwright/index.mjs";
const b = await chromium.launch({ channel: "chrome" });
const p = await b.newPage({ viewport: { width: 1280, height: 720 } });
p.on("console", (m) => { if (m.type() === "error") console.log("console:", m.text().slice(0, 140)); });
await p.goto("http://localhost:8090/", { waitUntil: "load", timeout: 60000 });
await p.waitForTimeout(6000);
console.log("home url", p.url(), "text:", (await p.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 300));
await p.screenshot({ path: "out/stack/yamcs_home.png" });
const inst = p.locator("text=fprime-project").first();
if (await inst.count()) { await inst.click(); await p.waitForTimeout(6000); console.log("after click url", p.url()); }
const hrefs = await p.$$eval("a[href]", (as) => [...new Set(as.map((a) => a.getAttribute("href")))]);
console.log(hrefs.filter((h) => h && h.startsWith("/")).join("\n"));
await p.screenshot({ path: "out/stack/yamcs_instance.png" });
await b.close();
