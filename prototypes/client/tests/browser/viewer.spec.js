import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile } from "node:fs/promises";
const fixture = JSON.parse(
  await readFile(new URL("../fixtures/state.json", import.meta.url), "utf8"),
);
const token = "synthetic-player-token";
const diagnostics = new WeakMap();
async function connect(page) {
  await page.locator("#match-id").fill(fixture.summary.match_id);
  await page.locator("#token").fill(token);
  await page.locator("#connect button").click();
  await expect(page.locator("#connection")).toHaveText(
    "Live · observing committed match updates",
  );
  await expect(page.locator("#board .tile")).toHaveCount(4);
}
async function upload(page, value) {
  await page.locator("#snapshot").setInputFiles({
    name: "state.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(value)),
  });
}
test.beforeEach(async ({ page, request }) => {
  await request.post("/__test/reset");
  const messages = { errors: [], expectedRevocation: false };
  diagnostics.set(page, messages);
  page.on("pageerror", (error) => {
    messages.errors.push(error.message);
  });
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    // A denied event reconnect is expected only in the explicit revocation scenario.
    if (
      messages.expectedRevocation &&
      message.location().url.endsWith("/events") &&
      message.text().includes("403")
    )
      return;
    messages.errors.push(message.text());
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204 }));
  await page.goto("/client/");
});
test.afterEach(async ({ page }) => {
  if (!(await page.locator("#disconnect").isDisabled()))
    await page.locator("#disconnect").click();
  expect(diagnostics.get(page).errors).toEqual([]);
});
test("inspects the board, navigates with keyboard, filters units, and passes accessibility", async ({
  page,
}) => {
  await connect(page);
  await expect(page.locator("#token")).toHaveValue("");
  await page.locator("#board .tile").first().click();
  await expect(page.locator("#inspector")).toContainText("Infantry");
  await expect(page.locator("#players")).toContainText("Power meter: 0");
  await expect(page.locator("#players")).toContainText("CO power: Inactive");
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#inspector")).toContainText("Tile (1, 0)");
  await page.locator("#filter").fill("Player 2");
  await expect(page.locator("#roster button")).toHaveCount(1);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(results.violations).toEqual([]);
  await expect(page.locator(".workspace")).toHaveScreenshot(
    "board-inspector.png",
  );
});
test("imports and exports a coherent snapshot, rejects incompatible data and shows unknown observations", async ({
  page,
}) => {
  await upload(page, fixture);
  await expect(page.locator("#connection")).toHaveText("Snapshot · read only");
  await expect(page.locator("#board .tile")).toHaveCount(4);
  const pending = page.waitForEvent("download");
  await page.locator("#export").click();
  const download = await pending;
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString();
  expect(JSON.parse(text)).toEqual(fixture);
  expect(text).not.toContain(token);
  const unknown = structuredClone(fixture);
  unknown.observation.game_state.battle.value.players[0].power_meter = {
    status: "unknown",
    value: null,
    reasons: ["Not observed"],
  };
  await upload(page, unknown);
  await expect(page.locator("#players")).toContainText(
    "Power meter: unknown: Not observed",
  );
  const invalid = structuredClone(fixture);
  invalid.observation.game_state.schema_version = 999;
  await upload(page, invalid);
  await expect(page.locator("#error")).toContainText(
    "Unsupported observation schema",
  );
  await expect(page.locator("#board .tile")).toHaveCount(0);
});
test("follows SSE revisions, clears stale screenshots, and loses access on revocation", async ({
  page,
  request,
}) => {
  await connect(page);
  await page.locator("#screenshot-button").click();
  await expect(page.locator("#screenshot")).toBeVisible();
  await request.post("/__test/advance");
  await expect(page.locator("#boundary")).toContainText("Revision 2 ·");
  await expect(page.locator("#screenshot")).toBeHidden();
  await page.locator("#screenshot-button").click();
  await expect(page.locator("#screenshot-label")).toHaveText(
    "Revision 2 · Frame 124",
  );
  diagnostics.get(page).expectedRevocation = true;
  await request.post("/__test/revoke");
  await expect(page.locator("#connection")).toContainText("Authorization lost");
  await expect(page.locator("#board .tile")).toHaveCount(0);
  await expect(page.locator("#screenshot")).toBeHidden();
});
test("reconnects and resynchronizes after a lost event stream", async ({
  page,
  request,
}) => {
  await connect(page);
  await request.post("/__test/advance?disconnect=true");
  await expect(page.locator("#boundary")).toContainText("Revision 2 ·");
  await expect(page.locator("#connection")).toHaveText(
    "Live · observing committed match updates",
  );
  expect(
    (await (await request.get("/__test/stats")).json()).connections,
  ).toBeGreaterThan(1);
});
test("rejects screenshot metadata from a different boundary", async ({
  page,
  request,
}) => {
  await connect(page);
  await request.post("/__test/screenshot-mismatch");
  await page.locator("#screenshot-button").click();
  await expect(page.locator("#error")).toContainText("does not match");
  await expect(page.locator("#screenshot")).toBeHidden();
});
