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
  await expect(page.locator("#action-unit")).toBeEnabled();
}
async function upload(page, value) {
  await page.locator("#snapshot").setInputFiles({
    name: "state.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(value)),
  });
}
async function rejectCapabilities(page, value, reason) {
  await page.route("**/v1/capabilities", (route) =>
    route.fulfill({ json: value }),
  );
  await page.locator("#match-id").fill(fixture.summary.match_id);
  await page.locator("#token").fill(token);
  await page.locator("#connect button").click();
  await expect(page.locator("#error")).toContainText(reason);
  await page.unroute("**/v1/capabilities");
}
test.beforeEach(async ({ page, request }) => {
  await request.post("/__test/reset");
  const messages = {
    errors: [],
    expectedRevocation: false,
    expectedDroppedReceipt: false,
  };
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
    if (
      messages.expectedDroppedReceipt &&
      message.location().url.endsWith("/commands") &&
      message.text().includes("net::ERR_FAILED")
    )
      return;
    if (
      messages.expectedActionRejection &&
      message.location().url.endsWith("/commands") &&
      message.text().includes("409")
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
test("keeps turn context visible while connection and match details can be expanded", async ({
  page,
}) => {
  await connect(page);
  await expect(page.getByLabel("Current turn")).toContainText("Your turn");
  await expect(page.getByLabel("Player status")).toContainText("Andy");
  await expect(page.getByLabel("Player status")).toContainText("funds");
  await expect(page.locator("#theme")).toBeHidden();
  await expect(page.locator("#match-id")).toBeHidden();
  await expect(page.locator("#players")).toBeHidden();
  await expect(page.locator("#refresh")).toBeVisible();
  await expect(page.locator("#disconnect")).toBeVisible();
  await page
    .getByText("Match details and player statistics", { exact: true })
    .click();
  await expect(page.locator("#players")).toBeVisible();
  await page
    .getByText("Connection, display, and snapshots", { exact: true })
    .click();
  await page.getByText("Connect to a match", { exact: true }).click();
  await expect(page.locator("#match-id")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "Skip to gameplay actions" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#draft-heading")).toBeFocused();
  await page.locator("#disconnect").click();
  await expect(page.locator("#match-id")).toBeVisible();
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
test("checks advertised contract and schema versions before connecting", async ({
  page,
  request,
}) => {
  const capabilities = await (await request.get("/v1/capabilities")).json();

  const unsupportedContract = structuredClone(capabilities);
  unsupportedContract.contract_version = 2;
  await rejectCapabilities(
    page,
    unsupportedContract,
    "Unsupported API contract version from capabilities: 2",
  );

  const unsupportedGameContract = structuredClone(capabilities);
  unsupportedGameContract.supported_game_contract_versions = [2];
  await rejectCapabilities(
    page,
    unsupportedGameContract,
    "Unsupported game contract version",
  );

  const unsupportedObservation = structuredClone(capabilities);
  unsupportedObservation.supported_match_observation_schema_versions = [2];
  await rejectCapabilities(
    page,
    unsupportedObservation,
    "Unsupported match observation schema version",
  );

  const unsupportedGameState = structuredClone(capabilities);
  unsupportedGameState.supported_game_state_schema_versions = [6];
  await rejectCapabilities(
    page,
    unsupportedGameState,
    "Unsupported game-state schema version",
  );

  const unavailableSse = structuredClone(capabilities);
  unavailableSse.http_sse.available = false;
  unavailableSse.http_sse.unavailable_reason = "Temporarily disabled";
  await rejectCapabilities(
    page,
    unavailableSse,
    "The server reports HTTP SSE unavailable: Temporarily disabled",
  );
});
test("validates the state schema returned by the live server", async ({
  page,
  request,
}) => {
  await request.post("/__test/corrupt-state");
  await page.locator("#match-id").fill(fixture.summary.match_id);
  await page.locator("#token").fill(token);
  await page.locator("#connect button").click();
  await expect(page.locator("#error")).toContainText(
    "Unsupported API contract version",
  );
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

test("submits gameplay actions with a revision and follows the command receipt", async ({
  page,
  request,
}) => {
  await connect(page);
  await page.getByRole("button", { name: "End turn", exact: true }).click();
  await expect(page.locator(".command-preview")).toContainText(
    "ready unit unused",
  );
  await expect(page.locator('[aria-label="Unused units"]')).toContainText(
    "Infantry · (0,0)",
  );
  await expect(page.locator(".command-preview")).toContainText("End your turn");
  await page.locator("#submit-action").click();
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
  await expect(page.locator(".command-result")).toContainText(
    "expected revision 1",
  );
  await expect(page.locator(".command-result")).toContainText(
    "Resulting revision 2",
  );
  await expect(page.locator("#boundary")).toContainText("Revision 2 ·");
  await expect(page.locator("#players")).toContainText(
    "Player 2 · two · Active",
  );
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(1);
});

test("confirms surrender explicitly and shows the finished command activity", async ({
  page,
}) => {
  await connect(page);
  await page.getByRole("button", { name: "Surrender", exact: true }).click();
  await expect(page.locator(".command-preview")).toContainText(
    "immediately forfeit this match",
  );
  await expect(page.locator(".command-preview [role=alert]")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Surrender match", exact: true }),
  ).toBeEnabled();
  await page.locator("#submit-action").click();
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
  await expect(page.locator('[aria-label="Command activity"]')).toContainText(
    "Completed and committed to the match.",
  );
});

test("retains recent command activity and distinguishes terminal results", async ({
  page,
  request,
}) => {
  await connect(page);
  const tile = (x, y) => page.locator(`#board [data-x="${x}"][data-y="${y}"]`);
  await tile(0, 0).click();
  await page
    .getByRole("button", { name: "Plan movement", exact: true })
    .click();
  await tile(1, 0).click();
  await page
    .getByRole("button", { name: "Choose action", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Unit actions" })
    .getByRole("button", { name: "Move & Wait", exact: true })
    .click();
  await expect(page.locator(".command-result")).toContainText(
    "Completed and committed to the match.",
  );

  await page.getByRole("button", { name: "End turn", exact: true }).click();
  await page.locator("#submit-action").click();
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
  const history = page.locator(".command-history");
  await expect(history).toContainText("Previous actions (1)");
  await history.locator("summary").click();
  await expect(history).toContainText("Move & Wait");
  await expect(history).toContainText("Resulting revision 2");
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(2);
});

test("keeps server error details expandable in command activity", async ({
  page,
}) => {
  await connect(page);
  await page.route("**/commands/*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const result = await response.json();
    await route.fulfill({
      response,
      json: {
        ...result,
        status: "rejected",
        error: {
          contract_version: 1,
          code: "action_rejected",
          message: "Synthetic server rejection",
          retryable: false,
          details: { reason: "Observed target is out of range", range: 4 },
        },
      },
    });
  });
  await page.getByRole("button", { name: "End turn", exact: true }).click();
  await page.locator("#submit-action").click();
  const details = page.locator(".command-result .command-error-details");
  await expect(details.locator("summary")).toContainText(
    "action_rejected: Synthetic server rejection",
  );
  await expect(details.locator("pre")).toBeHidden();
  await details.locator("summary").click();
  await expect(details.locator("pre")).toContainText(
    "Observed target is out of range",
  );
  await expect(details.locator("pre")).toContainText('"range": 4');
});

test("resets action drafts when the committed revision changes", async ({
  page,
  request,
}) => {
  await connect(page);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  await page
    .getByRole("button", { name: "Plan movement", exact: true })
    .click();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  await page
    .getByRole("button", { name: "Choose action", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Unit actions" }),
  ).toBeVisible();
  await request.post("/__test/advance");
  await expect(page.locator("#boundary")).toContainText("Revision 2");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".command-panel")).toContainText(
    "Match state changed",
  );
  await expect(page.locator("#board [data-route-step]")).toHaveCount(0);
});

test("safely retries an accepted command after losing its receipt", async ({
  page,
  request,
}) => {
  await connect(page);
  diagnostics.get(page).expectedDroppedReceipt = true;
  let dropFirstReceipt = true;
  await page.route("**/v1/matches/*/commands", async (route) => {
    if (!dropFirstReceipt) return route.continue();
    dropFirstReceipt = false;
    await route.fetch();
    await route.abort("failed");
  });
  await page.getByRole("button", { name: "End turn", exact: true }).click();
  await page.locator("#submit-action").click();
  await expect(page.locator(".command-result")).toContainText(
    "Command status: uncertain",
  );
  await page
    .getByRole("button", { name: "Retry safely with the same request ID" })
    .click();
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
  await expect(page.locator("#boundary")).toContainText("Revision 2 ·");
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(1);
  await page.unroute("**/v1/matches/*/commands");
});

for (const kind of ["move_wait", "move_attack", "move_capture"]) {
  test(`plans ${kind} through board activation and sends its explicit path`, async ({
    page,
  }) => {
    if (kind === "move_capture") {
      const state = structuredClone(fixture);
      state.observation.game_state.battle.value.properties.push({
        x: 1,
        y: 0,
        owner_slot: 0,
        terrain_class: 6,
      });
      await page.route("**/state", (route) => route.fulfill({ json: state }));
    }
    await connect(page);
    const tile = (x, y) =>
      page.locator(`#board [data-x="${x}"][data-y="${y}"]`);
    await tile(0, 0).click();
    await page
      .getByRole("button", { name: "Plan movement", exact: true })
      .click();
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#board [data-route-step]")).toHaveCount(1);
    await expect(tile(1, 0)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(tile(1, 0)).toHaveAttribute("data-route-step", "1");
    await page
      .getByRole("button", { name: "Choose action", exact: true })
      .click();
    const sent = page.waitForRequest(
      (request) =>
        request.url().endsWith("/commands") && request.method() === "POST",
    );
    const menu = page.getByRole("dialog", { name: "Unit actions" });
    if (kind === "move_attack") {
      await menu.getByRole("button", { name: "Attack", exact: true }).click();
      await tile(1, 1).click();
    } else
      await menu
        .getByRole("button", {
          name: kind === "move_capture" ? "Capture" : "Move & Wait",
          exact: true,
        })
        .click();
    const body = (await sent).postDataJSON();
    expect(body.expected_revision).toBe(1);
    expect(body.action).toMatchObject({
      kind,
      unit_id: "1",
      path: [{ contract_version: 1, x: 1, y: 0 }],
    });
    if (kind === "move_attack")
      expect(body.action.target).toEqual({ contract_version: 1, x: 1, y: 1 });
    await expect(page.locator(".command-result")).toContainText(
      "Command status: completed",
    );
  });
}

test("opens only empty owned factories and confirms affordable purchases", async ({
  page,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.players[0].funds = 1200;
  battle.properties.push({ x: 0, y: 1, terrain_class: 14, owner_slot: 1 });
  battle.properties[0].terrain_class = 14;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  await expect(page.getByRole("dialog", { name: "Purchase unit" })).toHaveCount(
    0,
  );
  await page.keyboard.press("Escape");
  await page.locator('#board [data-x="0"][data-y="1"]').click();
  const menu = page.getByRole("dialog", { name: "Purchase unit" });
  await expect(menu).toContainText("Funds: 1,200");
  await expect(menu.getByRole("button", { name: /^Mech / })).toBeDisabled();
  await menu.getByRole("button", { name: /^Infantry / }).click();
  await expect(
    page.getByRole("dialog", { name: "Confirm action" }),
  ).toContainText("Buy Infantry for 1,000 funds");
  await page.keyboard.press("Escape");
  await expect(menu.getByRole("button", { name: /^Infantry / })).toBeFocused();
  await page.keyboard.press("Enter");
  const sent = page.waitForRequest(
    (request) =>
      request.url().endsWith("/commands") && request.method() === "POST",
  );
  await page.locator("#submit-action").click();
  expect((await sent).postDataJSON()).toMatchObject({
    expected_revision: 1,
    action: {
      contract_version: 1,
      kind: "purchase",
      property: { contract_version: 1, x: 0, y: 1 },
      unit_type: "Infantry",
    },
  });
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
});

test("dismisses purchase drafts when selecting another tile or unit", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.players[0].funds = 5000;
  battle.properties.push({ x: 0, y: 1, terrain_class: 14, owner_slot: 1 });
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  const base = page.locator('#board [data-x="0"][data-y="1"]');
  await base.click();
  await page
    .getByRole("dialog", { name: "Purchase unit" })
    .getByRole("button", { name: /^Infantry / })
    .click();
  await expect(page.locator("#submit-action")).toBeEnabled();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await base.click();
  await base.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#inspector")).toContainText("Tile (1, 1)");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await base.click();
  await page.locator("#roster button").first().click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(0);
});

for (const relationship of ["own", "allied", "enemy"]) {
  test(`movement ${relationship === "enemy" ? "blocks enemy units" : `passes through ${relationship} units without ending on them`}`, async ({
    page,
    request,
  }) => {
    const state = structuredClone(fixture);
    const battle = state.observation.game_state.battle.value;
    battle.map.width = 3;
    battle.map.tiles = Array.from({ length: 6 }, (_, index) => ({
      x: index % 3,
      y: Math.floor(index / 3),
      terrain_class: 1,
      graphical_tile_id: 1,
      owner_slot: 0,
    }));
    battle.units[1].x = 1;
    battle.units[1].y = 0;
    battle.units[1].used_this_turn = true;
    if (relationship === "own") {
      battle.units[1].army_slot = 1;
      battle.units[1].unit_slot = 1;
      battle.units[1].reference = 2;
      for (const identity of state.observation.unit_identities)
        if (identity.reference === 65) identity.reference = 2;
    }
    if (relationship === "allied")
      battle.players[1].team_id = battle.players[0].team_id;
    await page.route("**/state", (route) => route.fulfill({ json: state }));
    await page.locator("#match-id").fill(fixture.summary.match_id);
    await page.locator("#token").fill(token);
    await page.locator("#connect button").click();
    await expect(page.locator("#board .tile")).toHaveCount(6);
    await page.locator('#board [data-x="0"][data-y="0"]').click();
    await page
      .getByRole("button", { name: "Plan movement", exact: true })
      .click();
    await page.locator('#board [data-x="1"][data-y="0"]').click();
    if (relationship === "enemy") {
      await expect(page.locator(".command-panel")).toContainText(
        "enemy unit blocks",
      );
      await expect(page.locator("#board [data-route-step]")).toHaveCount(1);
    } else {
      await expect(page.locator("#board [data-route-step]")).toHaveCount(2);
      await expect(page.locator(".route-editor")).toContainText(
        "choose an empty tile to finish",
      );
      await page.locator('#board [data-x="2"][data-y="0"]').click();
      await expect(page.locator(".route-editor")).toContainText(
        "(1,0) → (2,0)",
      );
      await page
        .getByRole("button", { name: "Choose action", exact: true })
        .click();
      await expect(
        page
          .getByRole("dialog", { name: "Unit actions" })
          .getByRole("button", { name: "Move & Wait", exact: true }),
      ).toBeEnabled();
    }
    expect((await (await request.get("/__test/stats")).json()).commands).toBe(
      0,
    );
  });
}

test("rejects impossible route steps and cancels movement without deselecting the unit", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.map.width = 5;
  battle.map.tiles = Array.from({ length: 10 }, (_, index) => ({
    x: index % 5,
    y: Math.floor(index / 5),
    terrain_class: index === 5 ? 7 : 1,
    graphical_tile_id: 1,
    owner_slot: 0,
  }));
  battle.units = [battle.units[0]];
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await page.locator("#match-id").fill(fixture.summary.match_id);
  await page.locator("#token").fill(token);
  await page.locator("#connect button").click();
  await expect(page.locator("#board .tile")).toHaveCount(10);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  await page
    .getByRole("button", { name: "Plan movement", exact: true })
    .click();
  await page.locator('#board [data-x="0"][data-y="1"]').click();
  await expect(page.locator(".command-panel")).toContainText(
    "cannot enter Sea",
  );
  await expect(page.locator("#board [data-route-step]")).toHaveCount(1);
  for (let x = 1; x <= 4; x++)
    await page.locator(`#board [data-x="${x}"][data-y="0"]`).click();
  await expect(page.locator(".command-panel")).toContainText("this unit has 3");
  await expect(page.locator("#board [data-route-step]")).toHaveCount(4);
  await page
    .getByRole("button", { name: "Cancel movement", exact: true })
    .click();
  await expect(page.locator("#board [data-route-step]")).toHaveCount(0);
  await expect(page.locator("#action-unit")).toHaveValue("1");
  await expect(
    page.getByRole("button", { name: "Plan movement", exact: true }),
  ).toBeVisible();
  await expect(page.locator("#submit-action")).toHaveCount(0);
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(0);
});

test("selects a unit and previews destinations without submitting commands", async ({
  page,
}) => {
  const state = structuredClone(fixture);
  state.observation.game_state.battle.value.units[0].internal_health = 67;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  const unit = page.locator('#board [data-x="0"][data-y="0"]');
  const empty = page.locator('#board [data-x="1"][data-y="0"]');
  await unit.click();
  await expect(page.getByLabel("Selected unit HP")).toHaveText("HP: 67/100");
  await expect(
    page.getByRole("button", { name: "Plan movement", exact: true }),
  ).toBeVisible();
  await expect(page.locator("#board [data-route-step]")).toHaveCount(0);
  await empty.click();
  await expect(page.getByLabel("Selected unit HP")).toHaveText("HP: 67/100");
  await expect(page.locator("#action-unit")).toHaveValue("1");
  await expect(page.locator("#board [data-route-step]")).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "Edit route manually" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#board [data-route-step]")).toHaveCount(0);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.locator("#board [data-route-step]")).toHaveCount(2);
  await page.keyboard.press("Escape");
  await unit.click();
  await expect(
    page
      .getByRole("dialog", { name: "Unit actions" })
      .getByRole("button", { name: "Move & Wait", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
});

test("restricts indirect attacks after movement and supports cancelling with Escape", async ({
  page,
}) => {
  const state = structuredClone(fixture);
  state.observation.game_state.battle.value.units[0].unit_type = 10;
  state.observation.game_state.battle.value.units[0].ammo = 9;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  await page.locator(".selection-lists").evaluate((node) => (node.open = true));
  await page.locator("#action-unit").focus();
  await page.locator("#action-unit").selectOption("1");
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  const menu = page.getByRole("dialog", { name: "Unit actions" });
  await expect(
    menu.getByRole("button", { name: "Attack", exact: true }),
  ).toBeEnabled();
  await menu.getByRole("button", { name: "Edit route manually" }).click();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  await page
    .getByRole("button", { name: "Choose action", exact: true })
    .click();
  await expect(
    menu.getByRole("button", { name: "Attack", exact: true }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.locator("#board [data-route-step]")).toHaveCount(0);
  await expect(page.locator(".command-panel")).toContainText(
    "Movement cancelled",
  );
});

test("keeps inspection available for opponents and used units and announces keyboard planning", async ({
  page,
}) => {
  await connect(page);
  await page.locator('#board [data-x="1"][data-y="1"]').click();
  await expect(page.locator("#inspector")).toContainText("Tile (1, 1)");
  await expect(page.locator("#action-unit")).toHaveValue("");
  await expect(page.locator(".command-panel")).toContainText(
    "Select one of your ready units",
  );
  await page.locator(".selection-lists").evaluate((node) => (node.open = true));
  await page.locator("#action-unit").focus();
  await page.locator("#action-unit").selectOption("1");
  await expect(page.locator("#action-unit")).toBeFocused();
  await page
    .getByRole("button", { name: "Plan movement", exact: true })
    .click();
  await page.locator(".route-editor details summary").click();
  await page.locator("#next-step").selectOption("1,0");
  await expect(page.locator(".route-editor")).toContainText(
    "Destination: (1,0)",
  );
  await page.getByRole("button", { name: "Undo step" }).click();
  await expect(page.locator(".route-editor")).toContainText("Act in place");
  await page
    .getByRole("button", { name: "Choose action", exact: true })
    .click();
  await expect(
    page
      .getByRole("dialog", { name: "Unit actions" })
      .getByRole("button", { name: "Move & Wait", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator('#board [data-x="0"][data-y="0"]')).toBeFocused();
  await page
    .getByText("Connection, display, and snapshots", { exact: true })
    .click();
  for (const theme of ["classic", "gruvbox"]) {
    await page.locator("#theme").selectOption(theme);
    for (const appearance of ["light", "dark"]) {
      await page.locator("#appearance").selectOption(appearance);
      await page
        .locator(".selection-lists")
        .evaluate((node) => (node.open = true));
      await page.locator("#action-unit").focus();
      await page.locator("#action-unit").selectOption("1");
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      expect(result.violations).toEqual([]);
    }
  }
  await page.setViewportSize({ width: 600, height: 900 });
  await expect(page.locator(".command-panel")).toBeVisible();
  const state = structuredClone(fixture);
  state.observation.game_state.battle.value.units[0].used_this_turn = true;
  state.summary.revision = state.observation.revision = 2;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await page.locator("#refresh").click();
  await expect(page.locator("#action-unit option")).toHaveCount(1);
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
  await page
    .getByText("Connection, display, and snapshots", { exact: true })
    .click();
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
  unknown.observation.game_state.battle.value.players[0].co_id = 255;
  await upload(page, unknown);
  await expect(page.locator("#perspective")).toContainText(
    "no authenticated player perspective",
  );
  await expect(page.locator("#players")).toContainText("Unknown player");
  await expect(page.locator("#players")).toContainText("Unknown CO (ID 255)");
  await expect(page.locator("#players .your-player")).toHaveCount(0);
});

test("refreshes the restored board and explains rollback after a failed action", async ({
  page,
}) => {
  await connect(page);
  await page.route("**/v1/matches/*/state", async (route) => {
    const response = await route.fetch();
    const state = await response.json();
    // Rollback advances the revision while restoring the original board/turn.
    state.observation.game_state.battle = structuredClone(
      fixture.observation.game_state.battle,
    );
    await route.fulfill({ response, json: state });
  });
  await page.route("**/commands/*", async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    await route.fulfill({
      response,
      json: {
        ...result,
        status: "rolled_back",
        error: {
          contract_version: 1,
          code: "recovery_required",
          message: "Navigation failed; restored the recovery checkpoint",
          retryable: false,
          details: { navigation_message: "Timed out waiting for Drop cursor" },
        },
      },
    });
  });
  await page.getByRole("button", { name: "End turn", exact: true }).click();
  await page.locator("#submit-action").click();
  await expect(page.locator(".command-result")).toContainText(
    "Command status: rolled_back",
  );
  await expect(page.locator(".activity-message")).toContainText(
    "changes were undone",
  );
  await expect(page.locator("#boundary")).toContainText("Revision 2 ·");
  await expect(page.locator("#players")).toContainText(
    "Player 1 · one · You · Active",
  );
  await expect(page.locator('#board [data-x="0"][data-y="0"]')).toHaveAttribute(
    "aria-label",
    /Infantry.*ready/,
  );
});

test("renders a local sprite pack and retains keyboard inspection", async ({
  page,
}) => {
  const atlas = `atlas-${"a".repeat(64)}.png`;
  const region = { x: 0, y: 0, width: 16, height: 32 };
  await page.route("**/client-sprites/manifest.json", (route) =>
    route.fulfill({
      json: {
        kind: "aw2-client-sprites",
        version: 1,
        atlas,
        width: 16,
        height: 32,
        terrain: { "1:0": region, "6:1": region, "6:2": region },
        units: {
          "1:1": { ...region, height: 16 },
          "1:2": { ...region, height: 16 },
        },
      },
    }),
  );
  await page.route(`**/client-sprites/${atlas}`, (route) =>
    route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="32"><rect width="16" height="32" fill="#508060"/></svg>',
    }),
  );
  await connect(page);
  await expect(page.locator(".sprite-terrain")).toHaveCount(4);
  await expect(page.locator(".sprite-unit")).toHaveCount(2);
  await expect(page.locator(".sprite-setup")).toHaveCount(0);
  await page.locator("#board .tile").first().click();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#inspector")).toContainText("Tile (1, 0)");
  await expect(page.locator('#board [data-x="1"][data-y="0"]')).toBeFocused();
});

test("clicking a distant destination builds a route without emulator input", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.map.width = 4;
  battle.map.height = 1;
  battle.map.tiles = Array.from({ length: 4 }, (_, x) => ({
    x,
    y: 0,
    terrain_class: 1,
    graphical_tile_id: 1,
    owner_slot: 0,
  }));
  battle.units = [battle.units[0]];
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await page.locator("#match-id").fill(fixture.summary.match_id);
  await page.locator("#token").fill(token);
  await page.locator("#connect button").click();
  await expect(page.locator("#board .tile")).toHaveCount(4);
  await page.locator('#board [data-x="0"]').click();
  await page.locator('#board [data-x="3"]').click();
  await expect(page.locator("#board [data-route-step]")).toHaveCount(4);
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(0);
  await page.getByRole("button", { name: "Edit route manually" }).click();
  await page.getByRole("button", { name: "Undo step" }).click();
  await expect(page.locator("#board [data-route-step]")).toHaveCount(3);
});

for (const kind of ["move_wait", "move_attack"]) {
  test(`context menu commits ${kind} without an extra confirmation`, async ({
    page,
    request,
  }) => {
    await connect(page);
    await page.locator('#board [data-x="0"][data-y="0"]').click();
    await page.locator('#board [data-x="1"][data-y="0"]').click();
    const menu = page.getByRole("dialog", { name: "Unit actions" });
    await expect(menu).toBeVisible();
    const requests = [];
    page.on("request", (req) => {
      if (req.url().endsWith("/commands") && req.method() === "POST")
        requests.push(req.postDataJSON());
    });
    if (kind === "move_attack") {
      await menu.getByRole("button", { name: "Attack", exact: true }).click();
      await expect(
        page.locator('#board [data-x="1"][data-y="1"]'),
      ).toBeFocused();
      await expect(page.locator('#board [data-x="1"][data-y="1"]')).toHaveClass(
        /attackable/,
      );
      await page.keyboard.press("Enter");
    } else
      await menu
        .getByRole("button", { name: "Move & Wait", exact: true })
        .click();
    await expect(page.locator(".command-result")).toContainText(
      "Command status: completed",
    );
    expect(requests).toHaveLength(1);
    expect(requests[0].action.kind).toBe(kind);
    expect(requests[0].action.path).toEqual([
      { contract_version: 1, x: 1, y: 0 },
    ]);
    expect((await (await request.get("/__test/stats")).json()).commands).toBe(
      1,
    );
  });
}

test("context menu cancellation returns through target, destination, and unit selection", async ({
  page,
  request,
}) => {
  await connect(page);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  const menu = page.getByRole("dialog", { name: "Unit actions" });
  await menu.getByRole("button", { name: "Attack", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(
    menu.getByRole("button", { name: "Move & Wait", exact: true }),
  ).toBeVisible();
  await menu.getByRole("button", { name: "Back", exact: true }).click();
  await expect(menu).toHaveCount(0);
  await expect(page.locator("#board [data-route-step]")).toHaveCount(0);
  await expect(page.locator('#board [data-x="0"][data-y="0"]')).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#action-unit")).toHaveValue("");
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(0);
});

for (const scale of [100, 200]) {
  test(`context menu supports keyboard and narrow placement at ${scale}% scale`, async ({
    page,
    request,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (let current = 100; current < scale; current += 10)
      await page.locator("#ui-scale-increase").click();
    await connect(page);
    const origin = page.locator('#board [data-x="0"][data-y="0"]');
    const destination = page.locator('#board [data-x="1"][data-y="0"]');
    await origin.click();
    await destination.click();
    const menu = page.getByRole("dialog", { name: "Unit actions" });
    await expect(
      menu.getByRole("button", { name: "Move & Wait", exact: true }),
    ).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(
      menu.getByRole("button", { name: "Attack", exact: true }),
    ).toBeFocused();
    const rect = await menu.boundingBox();
    expect(rect.x).toBeGreaterThanOrEqual(0);
    expect(rect.x + rect.width).toBeLessThanOrEqual(390);
    expect(rect.y + rect.height).toBeLessThanOrEqual(844);
    if (scale === 100) await origin.click({ button: "right" });
    else await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    expect((await (await request.get("/__test/stats")).json()).commands).toBe(
      0,
    );
  });
}

test("context menu submits Capture directly from an eligible observed property", async ({
  page,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.map.tiles.find((t) => t.x === 1 && t.y === 0).terrain_class = 6;
  battle.map.tiles.find((t) => t.x === 1 && t.y === 0).owner_slot = 2;
  battle.properties.push({ x: 1, y: 0, terrain_class: 6, owner_slot: 2 });
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  const capture = page
    .getByRole("dialog", { name: "Unit actions" })
    .getByRole("button", { name: "Capture", exact: true });
  await expect(capture).toBeEnabled();
  await page.unroute("**/state");
  const command = page.waitForRequest(
    (req) => req.url().endsWith("/commands") && req.method() === "POST",
  );
  await capture.click();
  expect((await command).postDataJSON().action.kind).toBe("move_capture");
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
});

test("unload passenger selection previews a drop before one final command", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.units[0].unit_type = 7;
  battle.units[0].cargo_references = [3];
  battle.units.push({
    ...battle.units[0],
    reference: 3,
    unit_slot: 3,
    unit_type: 1,
    embarked: true,
    used_this_turn: true,
    cargo_references: [],
  });
  state.observation.unit_identities.push({
    reference: 3,
    identity_id: "4",
    generation: 1,
  });
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await page.route("**/v1/capabilities", async (route) => {
    const response = await route.fetch();
    const capabilities = await response.json();
    capabilities.actions.push({
      contract_version: 1,
      name: "unload",
      implemented: true,
      available: true,
      verification: "synthetic",
      unavailable_reason: null,
    });
    await route.fulfill({ response, json: capabilities });
  });
  await connect(page);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  const menu = page.getByRole("dialog", { name: "Unit actions" });
  await menu.getByRole("button", { name: "Unload", exact: true }).click();
  await menu
    .getByRole("button", { name: "Passenger 1: Infantry", exact: true })
    .click();
  const drop = page.locator('#board [data-x="1"][data-y="0"]');
  await expect(drop).toHaveAttribute("data-drop-target", "true");
  await expect(drop).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(drop).toHaveAttribute("data-drop-selected", "D1");
  const submit = menu.getByRole("button", { name: "Unload selected cargo" });
  await expect(submit).toBeFocused();
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(0);
  await page.unroute("**/state");
  const command = page.waitForRequest(
    (req) => req.url().endsWith("/commands") && req.method() === "POST",
  );
  await submit.click();
  expect((await command).postDataJSON().action).toEqual({
    contract_version: 1,
    kind: "unload",
    transport_id: "1",
    path: [],
    drops: [
      {
        contract_version: 1,
        unit_id: "4",
        destination: { contract_version: 1, x: 1, y: 0 },
      },
    ],
  });
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
});

test("keeps feedback by the board and blocks repeated input while a receipt is pending", async ({
  page,
  request,
}) => {
  await connect(page);
  let release;
  const held = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/v1/matches/*/commands", async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
  });
  try {
    const unit = page.locator('#board [data-x="0"][data-y="0"]');
    await unit.click();
    await unit.click();
    await page
      .getByRole("dialog", { name: "Unit actions" })
      .getByRole("button", { name: "Move & Wait", exact: true })
      .evaluate((button) => {
        button.click();
        button.click();
      });
    await expect(page.locator(".board-column .command-result")).toContainText(
      "Command status: submitting",
    );
    await expect(
      page.getByRole("button", { name: "End turn", exact: true }),
    ).toBeDisabled();
    await expect(page.locator(".action-progress")).toBeVisible();
    await expect(page.locator(".action-progress")).toContainText(
      "Sending Move & Wait",
    );
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.locator('#board [data-x="1"][data-y="1"]').click();
    await expect(page.locator("#inspector")).toContainText("Tile (1, 1)");
    expect((await (await request.get("/__test/stats")).json()).commands).toBe(
      1,
    );
  } finally {
    release();
  }
  await expect(page.locator(".board-column .command-result")).toContainText(
    "Command status: completed",
  );
  await expect(page.locator(".action-progress")).toBeHidden();
  await page.unroute("**/v1/matches/*/commands");
});

test("distinguishes solid movement and striped attack overlays above terrain", async ({
  page,
}) => {
  await connect(page);
  await page.locator('#board [data-x="0"][data-y="0"]').click();
  const movement = page.locator("#board .movement-range").first();
  await expect(movement).toBeVisible();
  await expect(movement).toHaveCSS("border-top-style", "solid");
  await page
    .getByRole("button", { name: "Show attack range", exact: true })
    .click();
  const attack = page.locator("#board .firing-range").first();
  await expect(attack).toBeVisible();
  expect(
    await attack.evaluate((e) => getComputedStyle(e).backgroundImage),
  ).toContain("repeating-linear-gradient");
  await expect(page.getByLabel("Range legend")).toContainText(
    "Attack · diagonal stripes",
  );
});

test("does not offer Join into full-health Infantry but accepts a damaged used partner", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture),
    battle = state.observation.game_state.battle.value;
  battle.units[1] = {
    ...battle.units[0],
    reference: 2,
    unit_slot: 2,
    x: 1,
    y: 0,
  };
  state.observation.unit_identities[1].reference = 2;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await page.route("**/v1/capabilities", async (route) => {
    const value = await (await route.fetch()).json();
    value.actions.push({
      contract_version: 1,
      name: "join",
      implemented: true,
      available: true,
      verification: "synthetic",
      unavailable_reason: null,
    });
    await route.fulfill({ json: value });
  });
  await connect(page);
  const source = page.locator('#board [data-x="0"][data-y="0"]'),
    partner = page.locator('#board [data-x="1"][data-y="0"]');
  await source.click();
  await partner.click();
  await expect(
    page.getByRole("button", { name: "Join", exact: true }),
  ).toHaveCount(0);
  expect((await (await request.get("/__test/stats")).json()).commands).toBe(0);
  battle.units[1].internal_health = 50;
  battle.units[1].used_this_turn = true;
  state.summary.revision = state.observation.revision = 2;
  await page.locator("#refresh").click();
  await source.click();
  await partner.click();
  await expect(
    page
      .getByRole("dialog", { name: "Unit actions" })
      .getByRole("button", { name: "Join", exact: true }),
  ).toBeEnabled();
});

test("makes immediate action rejections visible and dismissible without stealing focus", async ({
  page,
}) => {
  await connect(page);
  diagnostics.get(page).expectedActionRejection = true;
  await page.route("**/v1/matches/*/commands", (route) =>
    route.fulfill({
      status: 409,
      json: {
        error: { message: "The match changed. Refresh before trying again." },
      },
    }),
  );
  await page.getByRole("button", { name: "End turn", exact: true }).click();
  await page.locator("#submit-action").click();
  const toast = page.locator(".game-toast");
  await expect(toast).toContainText("End turn could not be executed");
  await expect(toast).toContainText("The match changed.");
  await expect(
    toast.getByRole("button", { name: "Refresh board" }),
  ).toBeVisible();
  await toast.getByRole("button", { name: /Dismiss/ }).click();
  await expect(toast).toHaveCount(0);
});

test("keeps the acting unit distinct while inspecting and targeting elsewhere", async ({
  page,
}) => {
  await connect(page);
  const source = page.locator('#board [data-x="0"][data-y="0"]'),
    dest = page.locator('#board [data-x="1"][data-y="0"]');
  await source.click();
  await expect(source).toHaveAttribute("data-acting-unit", "true");
  await expect(source.locator(".acting-unit-marker")).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(source).toHaveAttribute("data-acting-unit", "true");
  await dest.click();
  await expect(source).toHaveAttribute("data-acting-unit", "true");
  await page
    .getByRole("dialog", { name: "Unit actions" })
    .getByRole("button", { name: "Attack", exact: true })
    .click();
  await expect(source).toHaveAttribute("data-acting-unit", "true");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-acting-unit]")).toHaveCount(0);
});

for (const type of [7, 20, 23, 22])
  test(`marks cargo on transport type ${type} and clears it after unloading`, async ({
    page,
  }) => {
    const state = structuredClone(fixture),
      battle = state.observation.game_state.battle.value;
    battle.units[0].unit_type = type;
    battle.units[0].cargo_references = [2];
    battle.units.push({
      ...battle.units[0],
      unit_type: 1,
      reference: 2,
      unit_slot: 2,
      embarked: true,
      cargo_references: [],
    });
    state.observation.unit_identities.push({
      reference: 2,
      identity_id: "3",
      generation: 1,
    });
    await page.route("**/state", (route) => route.fulfill({ json: state }));
    await connect(page);
    const transport = page.locator('#board [data-x="0"][data-y="0"]');
    await expect(transport.locator(".cargo-badge")).toHaveText("C1");
    await expect(transport).toHaveAccessibleName(
      /loaded transport, 1 passenger aboard/,
    );
    battle.units[0].cargo_references = [];
    battle.units[2].embarked = false;
    battle.units[2].x = 1;
    state.summary.revision = state.observation.revision = 2;
    await page.locator("#refresh").click();
    await expect(transport.locator(".cargo-badge")).toHaveCount(0);
  });

test("announces a new own turn without stealing focus or repeating on refresh/reconnect", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture),
    battle = state.observation.game_state.battle.value;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  await expect(page.locator(".toast-turn")).toHaveCount(0);
  battle.active_player_slot = 2;
  state.summary.revision = state.observation.revision = 2;
  await page.locator("#refresh").click();
  const tile = page.locator('#board [data-x="0"][data-y="0"]');
  await tile.focus();
  battle.active_player_slot = 1;
  battle.day = 2;
  state.summary.revision = state.observation.revision = 3;
  await request.post("/__test/advance");
  await expect(page.locator(".toast-turn")).toContainText("Your turn");
  await expect(tile).toBeFocused();
  await expect(page.locator(".toast-turn")).toContainText("Day 2");
  await page.getByRole("button", { name: "Dismiss Your turn" }).click();
  await page.locator("#refresh").click();
  await expect(page.locator(".toast-turn")).toHaveCount(0);
  await page.locator("#disconnect").click();
  await connect(page);
  await expect(page.locator(".toast-turn")).toHaveCount(0);
});
