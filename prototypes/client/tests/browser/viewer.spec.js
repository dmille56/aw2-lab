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
  unsupportedGameState.supported_game_state_schema_versions = [5];
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
  await expect(page.locator(".preview-summary")).toContainText(
    "End your turn and pass control",
  );
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
  await page.getByRole("button", { name: "Wait here" }).click();
  await page.locator("#submit-action").click();
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
  await expect(history).toContainText("Wait");
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
  await page.getByRole("button", { name: "Wait here" }).click();
  await expect(page.locator("#submit-action")).toBeEnabled();
  await request.post("/__test/advance");
  await expect(page.locator("#boundary")).toContainText("Revision 2");
  await expect(page.locator("#submit-action")).toHaveCount(0);
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
    if (kind === "move_capture") {
      await page.getByRole("button", { name: "Capture here" }).click();
    } else if (kind === "move_attack") {
      await page.getByRole("button", { name: "Choose attack target" }).click();
      await tile(1, 1).click();
      await expect(tile(1, 1)).toHaveAttribute("data-target", "true");
    } else await page.getByRole("button", { name: "Wait here" }).click();
    const sent = page.waitForRequest(
      (request) =>
        request.url().endsWith("/commands") && request.method() === "POST",
    );
    await page.locator("#submit-action").click();
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

test("lists only unoccupied supported bases for purchases", async ({
  page,
}) => {
  const state = structuredClone(fixture);
  const battle = state.observation.game_state.battle.value;
  battle.properties.push({ x: 0, y: 1, terrain_class: 14, owner_slot: 1 });
  battle.properties[0].terrain_class = 14;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  await page.locator(".selection-lists summary").click();
  expect(
    await page
      .locator("#purchase-property option")
      .evaluateAll((options) => options.map((option) => option.value)),
  ).toEqual(["", "0,1"]);
  await page.locator("#purchase-property").selectOption("0,1");
  await expect(page.locator("#purchase-unit-type")).toBeEnabled();
  await page.locator("#purchase-unit-type").selectOption("Infantry");
  await expect(page.locator(".command-preview")).toContainText(
    "Baseline cost: 1000",
  );
  const sent = page.waitForRequest(
    (request) =>
      request.url().endsWith("/commands") && request.method() === "POST",
  );
  await page.locator("#submit-action").click();
  expect((await sent).postDataJSON().action).toEqual({
    contract_version: 1,
    kind: "purchase",
    property: { contract_version: 1, x: 0, y: 1 },
    unit_type: "Infantry",
  });
  await expect(page.locator(".command-result")).toContainText(
    "Command status: completed",
  );
  state.summary.revision = state.observation.revision = 2;
  battle.units[0].x = 0;
  battle.units[0].y = 1;
  await page.locator("#refresh").click();
  await expect(page.locator("#purchase-property option")).toHaveText([
    "Choose a production facility",
    "(0,0)",
  ]);
});

test("dismisses base purchase drafts when inspecting another tile by click or keyboard", async ({
  page,
  request,
}) => {
  const state = structuredClone(fixture);
  state.observation.game_state.battle.value.properties.push({
    x: 0,
    y: 1,
    terrain_class: 14,
    owner_slot: 1,
  });
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  const base = page.locator('#board [data-x="0"][data-y="1"]');
  await base.click();
  await page.locator("#purchase-unit-type").selectOption("Infantry");
  await expect(page.locator("#submit-action")).toBeEnabled();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  await expect(page.locator("#purchase-unit-type")).toHaveCount(0);
  await expect(page.locator(".command-preview")).toHaveCount(0);
  await base.click();
  await expect(page.locator("#purchase-unit-type")).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#inspector")).toContainText("Tile (1, 1)");
  await expect(page.locator("#purchase-unit-type")).toHaveCount(0);
  await expect(page.locator(".command-preview")).toHaveCount(0);
  await base.click();
  await page.locator("#roster button").first().click();
  await expect(page.locator("#purchase-unit-type")).toHaveCount(0);
  await expect(page.locator("#action-unit")).toHaveValue("1");
  await expect(page.locator(".route-editor")).toContainText("Infantry");
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
      await expect(
        page.getByRole("button", { name: "Wait here" }),
      ).toBeDisabled();
      await expect(page.locator(".route-editor")).toContainText(
        "You can move through it",
      );
      await page.locator('#board [data-x="2"][data-y="0"]').click();
      await expect(page.locator("#board [data-route-step]")).toHaveCount(3);
      await page.getByRole("button", { name: "Wait here" }).click();
      await expect(page.locator("#submit-action")).toBeEnabled();
      await expect(page.locator(".command-preview")).toContainText(
        "(1,0) → (2,0)",
      );
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

test("selects a unit without entering movement planning and deselects when inspecting elsewhere", async ({
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
  await expect(page.getByLabel("Selected unit HP")).toHaveCount(0);
  await expect(page.locator("#action-unit")).toHaveValue("");
  await expect(page.locator(".route-editor")).toHaveCount(0);
  await unit.click();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator(".route-editor")).toHaveCount(0);
  await unit.click();
  await page.getByRole("button", { name: "Wait here" }).click();
  await expect(page.locator(".command-preview")).toContainText("stay in place");
});

test("restricts indirect attacks after movement and supports cancelling with Escape", async ({
  page,
}) => {
  const state = structuredClone(fixture);
  state.observation.game_state.battle.value.units[0].unit_type = 10;
  await page.route("**/state", (route) => route.fulfill({ json: state }));
  await connect(page);
  await page.locator(".selection-lists").evaluate((node) => (node.open = true));
  await page.locator("#action-unit").focus();
  await page.locator("#action-unit").selectOption("1");
  const attack = page.getByRole("button", { name: "Choose attack target" });
  await expect(attack).toBeEnabled();
  await page
    .getByRole("button", { name: "Plan movement", exact: true })
    .click();
  await page.locator('#board [data-x="1"][data-y="0"]').click();
  await expect(attack).toBeDisabled();
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
  await page.getByRole("button", { name: "Wait here" }).click();
  await expect(page.locator("#submit-action")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator("#draft-heading")).toBeFocused();
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
