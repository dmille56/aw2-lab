import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { TerrainDefense, terrainDefenseRating } from "../web/TerrainDefense";
import { DamagePreview } from "../web/DamagePreview";
import { UnitInspector } from "../web/Board";
import { validateState } from "../web/state";
import fixture from "./fixtures/state.json";
afterEach(cleanup);
it.each([
  [7, 0],
  [1, 1],
  [4, 2],
  [6, 3],
  [3, 4],
])("shows terrain %s defense %s", (terrainClass, rating) => {
  expect(terrainDefenseRating(terrainClass)).toBe(rating);
  const { container } = render(<TerrainDefense terrainClass={terrainClass} />);
  expect(container.querySelector("[data-terrain-defense]")).toHaveTextContent(
    `${rating}/4`,
  );
});
it.each([undefined, -1, 999, 1.5])(
  "leaves unknown terrain %s explicit",
  (terrainClass) => {
    render(<TerrainDefense terrainClass={terrainClass} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  },
);
it("shows base mountain defense before attacking an air unit and explains its lack of cover", () => {
  const b = structuredClone(
    validateState(fixture).observation!.game_state.battle.value!,
  );
  const defender = b.units[1];
  defender.unit_type = 19;
  b.map.tiles.find(
    (t) => t.x === defender.x && t.y === defender.y,
  )!.terrain_class = 3;
  const { container } = render(
    <DamagePreview
      battle={b}
      attacker={b.units[0]}
      defender={defender}
      path={[]}
    />,
  );
  expect(container.querySelector("[data-terrain-defense]")).toHaveTextContent(
    "4/4",
  );
  expect(
    screen.getByText("Air units receive no terrain defense."),
  ).toBeInTheDocument();
});
it("does not give embarked cargo terrain defense from its stale coordinates", () => {
  const snapshot = validateState(fixture);
  const unit = {
    ...snapshot.observation!.game_state.battle.value!.units[0],
    embarked: true,
  };
  render(<UnitInspector unit={unit} snapshot={snapshot} />);
  expect(screen.getByText("Unavailable while embarked")).toBeInTheDocument();
});
