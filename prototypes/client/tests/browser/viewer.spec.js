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
  await expect(page.locator("#players")).toContainText("Power uses: 0");
  await expect(page.locator("#players")).toContainText(
    "Charge thresholds: Power 32,400 charge units · Super 64,800 charge units (next use; reference only)",
  );
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
  unknown.observation.game_state.battle.value.players[0].power_use_counter = {
    status: "unknown",
    value: null,
    reasons: ["Counter not observed"],
  };
  unknown.observation.game_state.battle.value.players[0].active_power = 2;
  await upload(page, unknown);
  await expect(page.locator("#players")).toContainText(
    "Power meter: unknown: Not observed",
  );
  await expect(page.locator("#players")).toContainText(
    "Power uses: unknown: Counter not observed",
  );
  await expect(page.locator("#players")).toContainText(
    "CO power: Super Power active",
  );
  await expect(page.locator("#players")).toContainText(
    "Charge thresholds: Unavailable (use count unknown: Counter not observed)",
  );
  const invalid = structuredClone(fixture);
  invalid.observation.game_state.schema_version = 999;
  await upload(page, invalid);
  await expect(page.locator("#error")).toContainText(
    "Unsupported observation schema",
  );
  await expect(page.locator("#board .tile")).toHaveCount(0);
});
test("shows match facts together and explains unavailable observations", async ({
  page,
}) => {
  await upload(page, fixture);
  const values = page.locator("#match dl dd");
  await expect(values).toHaveText([
    "playable",
    "1",
    "Player 1",
    "clear",
    "false",
    "ready · Map input is recognized; individual action legality is not predicted",
  ]);
  await expect(page.locator("#players")).toContainText("Funds: 0");

  const withoutObservation = structuredClone(fixture);
  withoutObservation.observation = null;
  await upload(page, withoutObservation);
  await expect(values).toHaveText([
    "playable",
    "Unavailable (battle state not observed)",
    "Unavailable (battle state not observed)",
    "unavailable",
    "unavailable",
    "Unavailable (no committed observation)",
  ]);
  await expect(page.locator("#players")).toBeEmpty();
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

test("switches themes, follows system appearance, and persists explicit choices", async ({
  page,
}) => {
  const appearance = page.locator("#appearance");
  const theme = page.locator("#theme");
  await expect(theme.locator("option")).toHaveText(["Classic", "Gruvbox"]);
  await page.emulateMedia({ colorScheme: "light" });
  await appearance.selectOption("system");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(244, 246, 248)",
  );
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(16, 25, 35)",
  );
  await theme.selectOption("gruvbox");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(40, 40, 40)",
  );
  await appearance.selectOption("light");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(251, 241, 199)",
  );
  await page.reload();
  await expect(page.locator("#theme")).toHaveValue("gruvbox");
  await expect(page.locator("#appearance")).toHaveValue("light");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(251, 241, 199)",
  );
  await connect(page);
  await page.locator("#board .tile").first().click();
  await expect(page.locator("#board .tile.selected")).toHaveCount(1);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(results.violations).toEqual([]);
  await page.locator("#appearance").selectOption("dark");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(40, 40, 40)",
  );
  const darkResults = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(darkResults.violations).toEqual([]);
  await page.reload();
  await expect(page.locator("#theme")).toHaveValue("gruvbox");
  await expect(page.locator("#appearance")).toHaveValue("dark");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(40, 40, 40)",
  );
});

test("scales the whole interface independently, preserves focus, and persists", async ({
  page,
}) => {
  const scale = page.locator("#ui-scale-value");
  const decrease = page.locator("#ui-scale-decrease");
  const increase = page.locator("#ui-scale-increase");
  const reset = page.locator("#ui-scale-reset");
  const tileSize = page.locator("#zoom");

  await expect(scale).toHaveText("100%");
  await tileSize.fill("60");
  for (let step = 0; step < 5; step += 1) await decrease.click();
  await expect(scale).toHaveText("50%");
  await expect(decrease).toBeDisabled();
  const minimumAccessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(minimumAccessibility.violations).toEqual([]);

  await increase.focus();
  await page.keyboard.press("Enter");
  await expect(scale).toHaveText("60%");
  await expect(increase).toBeFocused();
  for (let step = 0; step < 13; step += 1) await increase.click();
  await expect(scale).toHaveText("190%");
  await increase.focus();
  await page.keyboard.press("Enter");
  await expect(scale).toHaveText("200%");
  await expect(increase).toBeDisabled();
  await decrease.focus();
  await page.keyboard.press("Enter");
  await expect(scale).toHaveText("190%");
  await expect(decrease).toBeFocused();
  await increase.click();
  await expect(scale).toHaveText("200%");
  await expect(tileSize).toHaveValue("60");
  await expect(reset).toBeVisible();
  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  expect(
    await page.evaluate(() =>
      document.documentElement.style.getPropertyValue("zoom"),
    ),
  ).toBe("2");
  const maximumAccessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(maximumAccessibility.violations).toEqual([]);

  await reset.click();
  await increase.click();
  await increase.click();
  await expect(scale).toHaveText("120%");
  await page.reload();
  await expect(scale).toHaveText("120%");
  expect(
    await page.evaluate(() =>
      document.documentElement.style.getPropertyValue("zoom"),
    ),
  ).toBe("1.2");
  await expect(tileSize).toHaveValue("58");
  await reset.click();
  await expect(scale).toHaveText("100%");
});

test("distinguishes your slot from the active player and toggles visible coordinates", async ({
  page,
}) => {
  await connect(page);
  await expect(page.locator("#perspective")).toContainText(
    "You: Player 1 · one",
  );
  await expect(page.locator("#players .your-player")).toContainText("Player 1");
  await expect(page.locator("#players")).toContainText("CO: Andy");
  await expect(page.locator("#board .coords").first()).toBeHidden();
  await page.getByLabel("Coordinates", { exact: true }).check();
  await expect(page.locator("#board .coords").first()).toBeVisible();
  const changed = structuredClone(fixture);
  changed.observation.game_state.battle.value.active_player_slot = 2;
  await page.route("**/state", (route) => route.fulfill({ json: changed }));
  await page.locator("#refresh").click();
  await expect(page.locator("#players .active-player")).toContainText(
    "Player 2",
  );
  await expect(page.locator("#players .your-player")).toContainText("Player 1");
  await expect(
    page.locator("#board button[data-your-unit='true']"),
  ).toHaveCount(1);
});

test("fits a full board, responds to resize, and preserves keyboard selection", async ({
  page,
}) => {
  const large = structuredClone(fixture);
  large.observation.game_state.battle.value.units[0].used_this_turn = true;
  const map = large.observation.game_state.battle.value.map;
  map.width = 16;
  map.height = 15;
  map.tiles = Array.from({ length: 240 }, (_, i) => ({
    ...map.tiles[0],
    x: i % 16,
    y: Math.floor(i / 16),
  }));
  await upload(page, large);
  await expect(page.locator("#board .tile")).toHaveCount(240);
  const initial = Number(await page.locator("#zoom").inputValue());
  expect(initial).toBeGreaterThan(36);
  const board = await page.locator("#board").boundingBox();
  const viewport = await page.locator("#map-scroll").boundingBox();
  expect(board.width).toBeLessThanOrEqual(viewport.width);
  expect(board.height).toBeLessThanOrEqual(600);
  await page.locator("#board .tile").first().click();
  await page.setViewportSize({ width: 900, height: 960 });
  await expect(page.locator("#zoom")).toHaveValue("36");
  const tileBounds = await page.locator("#board .tile").first().boundingBox();
  const healthBounds = await page
    .locator("#board .unit-health")
    .first()
    .boundingBox();
  expect(healthBounds.x).toBeGreaterThanOrEqual(tileBounds.x);
  expect(healthBounds.x + healthBounds.width).toBeLessThanOrEqual(
    tileBounds.x + tileBounds.width,
  );
  expect(healthBounds.y + healthBounds.height).toBeLessThanOrEqual(
    tileBounds.y + tileBounds.height,
  );
  await expect(page.locator("#board .tile").first()).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#inspector")).toContainText("Tile (1, 0)");
  await page.locator("#zoom").fill("60");
  await expect(page.locator("#fit-map")).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await page.locator("#fit-map").click();
  await expect(page.locator("#zoom")).toHaveValue("36");
  await page.setViewportSize({ width: 1280, height: 960 });
  await expect(page.locator("#zoom")).toHaveValue(String(initial));
});

test("shows explicit unknown names and snapshot perspective", async ({
  page,
}) => {
  const unknown = structuredClone(fixture);
  unknown.summary.slots[0].display_name = null;
  unknown.observation.game_state.battle.value.players[0].co_id = 18;
  await upload(page, unknown);
  await expect(page.locator("#perspective")).toContainText(
    "no authenticated player perspective",
  );
  await expect(page.locator("#players")).toContainText("Unknown player");
  await expect(page.locator("#players")).toContainText("Unknown CO (ID 18)");
  await expect(page.locator("#players .your-player")).toHaveCount(0);
});
