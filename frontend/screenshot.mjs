/**
 * Playwright screenshot for Day 11-12 review.
 * Generates a 4-stop Dublin plan, then:
 *   wide: mid-drag screenshot (gripper visible, stop 2 being dragged to pos 3)
 *   narrow: resting state after plan loads (gripper visible, stay/leave wrap)
 */
import { chromium } from "playwright";

const URL = "http://localhost:3000";

const CITY = "Dublin, Ireland";
const STOPS = [
  "Trinity College Dublin",
  "Guinness Storehouse",
  "St. Patrick's Cathedral",
  "Temple Bar",
];
const START_TIME = "2026-05-17T10:00";

async function fillAndSubmit(page) {
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.fill('input[placeholder="Dublin, Ireland"]', CITY);

  // Fill stops — 2 exist by default, need 4
  for (let i = 0; i < STOPS.length; i++) {
    if (i >= 2) {
      await page.click("text=+ Add stop");
      await page.waitForTimeout(80);
    }
    const inputs = await page.locator('input[placeholder^="Stop"]').all();
    await inputs[i].fill(STOPS[i]);
  }

  // Set start time via JS
  await page.evaluate((val) => {
    const el = document.querySelector('input[type="datetime-local"]');
    if (el) {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")
        .set.call(el, val);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }, START_TIME);

  await page.click('button[type="submit"]');
  await page.waitForSelector("ol", { timeout: 45000 });
  await page.waitForTimeout(600);
}

async function run() {
  const browser = await chromium.launch({ headless: true });

  // ── Wide: mid-drag screenshot ──────────────────────────────────────────────
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    await fillAndSubmit(page);

    // Locate all gripper buttons in the timeline
    const grippers = await page.locator('button[aria-label="Drag to reorder"]').all();
    console.log(`Found ${grippers.length} drag handles`);

    if (grippers.length >= 2) {
      // Drag stop 2 (index 1) toward stop 3 (index 2)
      const grip2 = await grippers[1].boundingBox();
      const grip3 = grippers[2] ? await grippers[2].boundingBox() : null;

      if (grip2) {
        const startX = grip2.x + grip2.width / 2;
        const startY = grip2.y + grip2.height / 2;
        const targetY = grip3
          ? grip3.y + grip3.height / 2 + 20
          : startY + 80;

        // Start drag
        await page.mouse.move(startX, startY);
        await page.mouse.down();
        // Move in steps so dnd-kit's activation constraint fires
        await page.mouse.move(startX + 1, startY, { steps: 2 });
        await page.mouse.move(startX, targetY, { steps: 12 });
        await page.waitForTimeout(200);

        // Screenshot mid-drag
        await page.screenshot({ path: "screenshot_wide_drag.png", fullPage: true });
        console.log("Saved screenshot_wide_drag.png (1280px, mid-drag)");

        // Release
        await page.mouse.up();
        await page.waitForTimeout(500);
      }
    }

    // Also save a resting-state wide screenshot
    await page.screenshot({ path: "screenshot_wide.png", fullPage: true });
    console.log("Saved screenshot_wide.png (1280px, resting)");
    await ctx.close();
  }

  // ── Narrow: resting state ──────────────────────────────────────────────────
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
    const page = await ctx.newPage();
    await fillAndSubmit(page);
    await page.screenshot({ path: "screenshot_narrow.png", fullPage: true });
    console.log("Saved screenshot_narrow.png (390px)");
    await ctx.close();
  }

  await browser.close();
}

run().catch((e) => { console.error(e); process.exit(1); });
