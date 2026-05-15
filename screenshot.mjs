/**
 * Quick Playwright script: fill the RouteWright form with a Dublin plan,
 * submit it, wait for the timeline, then screenshot at wide and narrow.
 * Run: node screenshot.mjs
 */
import { chromium } from "playwright";

const URL = "http://localhost:3000";

// Dublin tourist day trip
const CITY = "Dublin, Ireland";
const STOPS = [
  "Trinity College Dublin",
  "Guinness Storehouse",
  "Temple Bar",
];
// Use a fixed future date that works with datetime-local input
const START_TIME = "2026-05-17T10:00";

async function run() {
  const browser = await chromium.launch({ headless: true });

  for (const [label, width] of [["wide", 1280], ["narrow", 390]]) {
    const ctx = await browser.newContext({
      viewport: { width, height: 900 },
    });
    const page = await ctx.newPage();

    await page.goto(URL, { waitUntil: "networkidle" });

    // Fill city
    await page.fill('input[placeholder="Dublin, Ireland"]', CITY);

    // Fill stop inputs — there are 2 by default, we need 3
    const stopInputs = await page.locator('input[placeholder^="Stop"]').all();
    for (let i = 0; i < STOPS.length; i++) {
      if (i >= stopInputs.length) {
        await page.click("text=+ Add stop");
        await page.waitForTimeout(100);
      }
      const inputs = await page.locator('input[placeholder^="Stop"]').all();
      await inputs[i].fill(STOPS[i]);
    }

    // Set start time via JS (datetime-local quirks)
    await page.evaluate((val) => {
      const el = document.querySelector('input[type="datetime-local"]');
      if (el) {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype,
          "value"
        ).set;
        nativeInputValueSetter.call(el, val);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }, START_TIME);

    // Transit is already selected by default

    // Submit
    await page.click('button[type="submit"]');

    // Wait for timeline (up to 30s for API round trip)
    await page.waitForSelector("ol", { timeout: 30000 });
    // Small extra wait for layout to settle
    await page.waitForTimeout(500);

    await page.screenshot({
      path: `screenshot_${label}.png`,
      fullPage: true,
    });
    console.log(`Saved screenshot_${label}.png (${width}px wide)`);
    await ctx.close();
  }

  await browser.close();
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
