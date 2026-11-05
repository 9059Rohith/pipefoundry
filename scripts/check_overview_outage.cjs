// Browser regression: inject provider failures, then use the real public validator.
// PLAYWRIGHT_MODULE and CHROME_EXECUTABLE select an already installed browser.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");

(async () => {
  const base = process.env.WORKBENCH_URL || "http://127.0.0.1:8125";
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_EXECUTABLE
      ? { executablePath: process.env.CHROME_EXECUTABLE }
      : {}),
  });
  try {
    for (const width of [390, 1440]) {
      for (const code of [429, 502]) {
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        page.setDefaultTimeout(10000);
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        const message = code === 429
          ? "GitHub rate limit reached and no usable cached evidence exists. Try again in 1820 seconds."
          : "Could not reach GitHub. Retry the inspection.";
        // These are deliberate outage responses, never synthetic source observations.
        await page.route("**/workbench/api/github?**", (route) => route.fulfill({
          status: code,
          contentType: "application/json",
          headers: { "Retry-After": "1820" },
          body: JSON.stringify({ detail: message }),
        }));
        assert.equal((await page.goto(`${base}/workbench/overview`)).status(), 200);
        await page.getByRole("heading", { name: "Repository inspection", exact: true }).waitFor();
        const metrics = page.locator(".metrics .metric");
        assert.equal(await metrics.count(), 4);
        assert.deepEqual(await metrics.evaluateAll((rows) => rows.map((row) =>
          Array.from(row.children, (child) => child.tagName))),
        Array.from({ length: 4 }, () => ["DT", "DD"]));
        for (const value of await metrics.locator("dd").allTextContents()) {
          assert.match(value, /^Unavailable/);
          assert.doesNotMatch(value, /Invalid Date|undefined|NaN/);
        }
        assert.ok((await page.locator("#content").innerText()).includes(message));
        assert.equal(await page.evaluate(() =>
          document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
        await page.locator('#content .step[href="/workbench/editor"]').click();
        await page.getByRole("button", { name: "Validate configuration" }).click();
        await page.getByText("Validated session draft", { exact: true }).waitFor();
        await page.getByRole("link", { name: "Inspect manifest", exact: true }).click();
        await page.locator("pre").filter({ hasText: "CronJob" }).first().waitFor();
        assert.deepEqual(errors, []);
        assert.equal(await page.evaluate(() =>
          document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
        console.log(JSON.stringify({ width, injected_status: code,
          metrics: 4, validation: "accepted", manifest: "CronJob", pageerrors: errors }));
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
